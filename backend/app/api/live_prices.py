"""
Live pricing endpoints — real-time data from Nexar, DigiKey, OEMsecrets, TrustedParts.

These endpoints supplement (and eventually replace) the static HuggingFace dataset
with live API calls. They gracefully degrade: if a key is missing, that source is skipped.
As of this wiring pass, Nexar, DigiKey and OEMsecrets are genuinely live in this
deployment — this is real production traffic, not a stub.

Source priority:
  1. Nexar       — multi-distributor GraphQL (covers DigiKey, Mouser, Arrow, Farnell, LCSC in one call)
  2. OEMsecrets  — 40+ additional distributors in one call (free with approval)
  3. DigiKey     — official DK API for lifecycle_status + lead_time_weeks not in Nexar
  4. TrustedParts— authorized-distributor-only results, feeds is_authorized risk flag

Endpoints and their frontend consumers:
  GET  /live-prices/{mpn}       — SchedulerPage.tsx "Get live price" / "Refresh live
                                   price" panel on the component detail view. Shows
                                   real per-distributor offers (SKU, stock, price
                                   breaks, lead time) beside the static 2024 snapshot,
                                   with explicit not-found / no-sources-configured states.
  POST /live-prices/bom         — CartPage.tsx "Check live pricing" bulk action:
                                   compares each cart line's locked-in snapshot price
                                   against today's best live offer.
  POST /live-prices/{mpn}/sync  — SchedulerPage.tsx "Save live prices to catalog" —
                                   persists a fetched live offer into the component's
                                   DistributorOffer rows so the static snapshot is
                                   upgraded, not just displayed once and discarded.
"""

import logging
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.api.auth import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-prices", tags=["live-prices"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class SourceStatus(StrEnum):
    ok = "ok"                       # source was configured, was called, no error
    error = "error"                 # source was configured but the call raised/failed
    skipped = "skipped"             # source was configured but intentionally not called
    not_configured = "not_configured"  # no API key/credentials present


class SourceReport(BaseModel):
    """Per-source outcome for a single live-pricing fetch.

    Lets a caller distinguish "this source has zero offers for this part"
    from "this source errored and we don't actually know" — the previous
    implementation swallowed every per-source exception into a bare
    `print()`, so both cases looked identical: a 200 with fewer offers.
    """
    name: str
    configured: bool
    status: SourceStatus
    offer_count: int = 0
    error: Optional[str] = None


class LiveOffer(BaseModel):
    distributor: str
    sku: Optional[str]
    stock: int
    moq: int
    price: float
    currency: str
    is_authorized: bool
    price_breaks: List[Dict[str, Any]] = []
    lead_time_weeks: Optional[int] = None
    lifecycle_status: Optional[str] = None
    datasheet_url: Optional[str] = None
    source: str  # "nexar", "digikey", "mouser", "oemsecrets", "trustedparts"


class LivePriceResponse(BaseModel):
    mpn: str
    total_offers: int
    sources_used: List[str]
    offers: List[LiveOffer]
    cached: bool = False
    sources: List[SourceReport] = []
    all_sources_failed: bool = False


class BomItem(BaseModel):
    mpn: str
    quantity: int = 1


class BomRequest(BaseModel):
    items: List[BomItem]


class BomPriceResponse(BaseModel):
    results: Dict[str, LivePriceResponse]
    total_mpns: int
    sources_used: List[str]
    sources: List[SourceReport] = []
    all_sources_failed: bool = False


class SyncPricesResponse(BaseModel):
    mpn: Optional[str] = None
    live_offers_found: Optional[int] = None
    db_offers_updated: Optional[int] = None
    db_offers_created: Optional[int] = None
    sources: List[str] = []
    updated: Optional[int] = None
    message: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

async def _fetch_live_offers(mpn: str) -> Tuple[List[Dict], List[str], List[SourceReport]]:
    """
    Core offer-fetching logic shared by get_live_prices and sync_component_prices.

    Returns (all_offers, sources_used, source_reports).

    Every source's outcome — ok / error / not_configured, plus offer count and
    error message — is captured in `source_reports` rather than being caught
    and printed. Raises HTTPException if:
      - no sources are configured at all (503), or
      - every configured source errored, i.e. we genuinely don't know whether
        offers exist (502), or
      - every configured source ran cleanly but none had offers (404).
    In all three cases the structured per-source reports ride along in the
    exception detail so a caller can see *why*, not just that it failed.
    """
    all_offers: List[Dict] = []
    sources_used: List[str] = []
    reports: List[SourceReport] = []

    def _record(name: str, offers: List[Dict]) -> None:
        reports.append(SourceReport(name=name, configured=True, status=SourceStatus.ok, offer_count=len(offers)))
        all_offers.extend(offers)
        if offers:
            sources_used.append(name)

    def _record_error(name: str, exc: Exception) -> None:
        logger.warning("[live_prices] %s source failed for %s: %s", name, mpn, exc)
        reports.append(SourceReport(name=name, configured=True, status=SourceStatus.error, error=str(exc)))

    # ── Nexar (multi-distributor GraphQL) ──────────────────────────────────────
    if settings.NEXAR_CLIENT_ID and settings.NEXAR_CLIENT_SECRET:
        try:
            from app.core.clients.nexar_client import NexarClient
            client = NexarClient(settings.NEXAR_CLIENT_ID, settings.NEXAR_CLIENT_SECRET)
            part = await client.search_mpn(mpn)
            offers = client.parse_offers(part) if part else []
            for o in offers:
                o["source"] = "nexar"
            _record("nexar", offers)
        except Exception as e:
            _record_error("nexar", e)
    else:
        reports.append(SourceReport(name="nexar", configured=False, status=SourceStatus.not_configured))

    # ── OEMsecrets (140+ distributors in one call) ─────────────────────────────
    if settings.OEMSECRETS_API_KEY:
        try:
            from app.core.clients.oemsecrets_client import OEMSecretsClient
            client = OEMSecretsClient(settings.OEMSECRETS_API_KEY)
            offers = await client.search_mpn(mpn)
            for o in offers:
                o["source"] = "oemsecrets"
                if "is_authorized" not in o:
                    o["is_authorized"] = False
            _record("oemsecrets", offers)
        except Exception as e:
            _record_error("oemsecrets", e)
    else:
        reports.append(SourceReport(name="oemsecrets", configured=False, status=SourceStatus.not_configured))

    # ── DigiKey (official API — best for DK-specific data) ────────────────────
    if settings.DIGIKEY_CLIENT_ID and settings.DIGIKEY_CLIENT_SECRET:
        try:
            from app.core.clients.digikey_client import DigiKeyClient
            client = DigiKeyClient(
                settings.DIGIKEY_CLIENT_ID,
                settings.DIGIKEY_CLIENT_SECRET,
                sandbox=settings.DIGIKEY_SANDBOX,
            )
            product = await client.search_mpn(mpn)
            offers = []
            if product:
                offer = client.parse_offer(product)
                offer["source"] = "digikey"
                offers = [offer]
            _record("digikey", offers)
        except Exception as e:
            _record_error("digikey", e)
    else:
        reports.append(SourceReport(name="digikey", configured=False, status=SourceStatus.not_configured))

    # ── TrustedParts (authorized-only, feeds is_authorized risk flag) ────────────
    if settings.TRUSTEDPARTS_API_KEY:
        try:
            from app.core.clients.trustedparts_client import TrustedPartsClient
            client = TrustedPartsClient(settings.TRUSTEDPARTS_API_KEY)
            offers = await client.search_mpn(mpn)
            for o in offers:
                o["source"] = "trustedparts"
            _record("trustedparts", offers)
        except Exception as e:
            _record_error("trustedparts", e)
    else:
        reports.append(SourceReport(name="trustedparts", configured=False, status=SourceStatus.not_configured))

    configured_reports = [r for r in reports if r.configured]
    errored_reports = [r for r in configured_reports if r.status == SourceStatus.error]
    all_sources_failed = bool(configured_reports) and len(errored_reports) == len(configured_reports)

    if not configured_reports:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "No live pricing sources configured. Add at least one API key to .env.",
                "sources": [r.model_dump() for r in reports],
            },
        )
    if all_sources_failed:
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"All {len(configured_reports)} configured live pricing source(s) failed for {mpn}.",
                "all_sources_failed": True,
                "sources": [r.model_dump() for r in reports],
            },
        )
    if not all_offers:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"No offers found for MPN: {mpn}",
                "sources": [r.model_dump() for r in reports],
            },
        )

    return all_offers, sources_used, reports


@router.get("/{mpn}", response_model=LivePriceResponse)
async def get_live_prices(
    mpn: str,
    include_unauthorized: bool = Query(True, description="Include gray market offers"),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch real-time pricing for a single MPN from all configured sources.

    Sources are tried in priority order. Results are merged and deduplicated.
    Returns offers sorted cheapest first.
    """
    all_offers, sources_used, reports = await _fetch_live_offers(mpn)

    # Merge + deduplicate by (distributor, sku)
    merged = _deduplicate_offers(all_offers)

    if not include_unauthorized:
        merged = [o for o in merged if o.get("is_authorized", False)]

    # Sort by price
    merged.sort(key=lambda o: o.get("price") or 9999)

    return LivePriceResponse(
        mpn=mpn,
        total_offers=len(merged),
        sources_used=list(set(sources_used)),
        offers=[_to_live_offer(o) for o in merged],
        sources=reports,
    )


@router.post("/bom", response_model=BomPriceResponse)
async def get_bom_prices(
    body: BomRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Bulk BOM pricing — fetch live prices for multiple MPNs.

    Uses Nexar's supMultiMatch query when available (single GraphQL call for all MPNs).
    Falls back to sequential individual lookups for other sources.
    """
    if not body.items:
        raise HTTPException(status_code=400, detail="BOM is empty")

    mpns = [item.mpn for item in body.items]
    results: Dict[str, LivePriceResponse] = {}
    all_sources: List[str] = []

    # ── Nexar bulk (preferred — one call for all MPNs, via supMultiMatch) ──────
    nexar_configured = bool(settings.NEXAR_CLIENT_ID and settings.NEXAR_CLIENT_SECRET)
    nexar_client = None
    nexar_lines: Dict[str, Dict[str, Any]] = {}  # mpn -> {"part": ..., "error": ...}
    nexar_bulk_error: Optional[str] = None
    nexar_bulk_offer_count = 0

    if nexar_configured:
        from app.core.clients.nexar_client import NexarClient
        nexar_client = NexarClient(settings.NEXAR_CLIENT_ID, settings.NEXAR_CLIENT_SECRET)
        try:
            bom_results = await nexar_client.search_bom(mpns)
            for item in bom_results:
                ref = item.get("reference") or ""
                if ref:
                    nexar_lines[ref] = item
                    if item.get("part"):
                        nexar_bulk_offer_count += len(nexar_client.parse_offers(item["part"]))
        except Exception as e:
            logger.warning("[live_prices] Nexar BOM error: %s", e)
            nexar_bulk_error = str(e)

    # ── OEMsecrets per-MPN (no bulk endpoint) ───────────────────────────────────
    oemsecrets_configured = bool(settings.OEMSECRETS_API_KEY)
    oemsecrets_errors: List[str] = []
    oemsecrets_offer_count = 0

    for mpn in mpns:
        offers: List[Dict] = []
        sources: List[str] = []
        mpn_reports: List[SourceReport] = []

        # ── Nexar: use the bulk result for this line ────────────────────────────
        if nexar_configured:
            if nexar_bulk_error:
                mpn_reports.append(SourceReport(
                    name="nexar", configured=True, status=SourceStatus.error, error=nexar_bulk_error,
                ))
            else:
                line = nexar_lines.get(mpn)
                line_error = line.get("error") if line else None
                if line_error:
                    mpn_reports.append(SourceReport(
                        name="nexar", configured=True, status=SourceStatus.error, error=str(line_error),
                    ))
                else:
                    part = line.get("part") if line else None
                    parsed = nexar_client.parse_offers(part) if part and nexar_client else []
                    for o in parsed:
                        o["source"] = "nexar"
                    offers.extend(parsed)
                    if parsed:
                        sources.append("nexar")
                    mpn_reports.append(SourceReport(
                        name="nexar", configured=True, status=SourceStatus.ok, offer_count=len(parsed),
                    ))
        else:
            mpn_reports.append(SourceReport(name="nexar", configured=False, status=SourceStatus.not_configured))

        # ── OEMsecrets ───────────────────────────────────────────────────────────
        if oemsecrets_configured:
            try:
                from app.core.clients.oemsecrets_client import OEMSecretsClient
                oemc = OEMSecretsClient(settings.OEMSECRETS_API_KEY)
                oem_offers = await oemc.search_mpn(mpn)
                for o in oem_offers:
                    o["source"] = "oemsecrets"
                offers.extend(oem_offers)
                oemsecrets_offer_count += len(oem_offers)
                if oem_offers:
                    sources.append("oemsecrets")
                mpn_reports.append(SourceReport(
                    name="oemsecrets", configured=True, status=SourceStatus.ok, offer_count=len(oem_offers),
                ))
            except Exception as e:
                logger.warning("[live_prices] OEMsecrets BOM error for %s: %s", mpn, e)
                oemsecrets_errors.append(str(e))
                mpn_reports.append(SourceReport(
                    name="oemsecrets", configured=True, status=SourceStatus.error, error=str(e),
                ))
        else:
            mpn_reports.append(SourceReport(name="oemsecrets", configured=False, status=SourceStatus.not_configured))

        merged = _deduplicate_offers(offers)
        merged.sort(key=lambda o: o.get("price") or 9999)
        all_sources.extend(sources)

        configured_mpn_reports = [r for r in mpn_reports if r.configured]
        mpn_all_failed = bool(configured_mpn_reports) and all(
            r.status == SourceStatus.error for r in configured_mpn_reports
        )

        results[mpn] = LivePriceResponse(
            mpn=mpn,
            total_offers=len(merged),
            sources_used=list(set(sources)),
            offers=[_to_live_offer(o) for o in merged],
            sources=mpn_reports,
            all_sources_failed=mpn_all_failed,
        )

    # ── Top-level source summary (one entry per source, aggregated across the
    # whole BOM — per-MPN detail lives in each result's own `sources` list) ────
    top_reports: List[SourceReport] = []
    if nexar_configured:
        if nexar_bulk_error:
            top_reports.append(SourceReport(
                name="nexar", configured=True, status=SourceStatus.error,
                error=nexar_bulk_error,
            ))
        else:
            top_reports.append(SourceReport(
                name="nexar", configured=True, status=SourceStatus.ok, offer_count=nexar_bulk_offer_count,
            ))
    else:
        top_reports.append(SourceReport(name="nexar", configured=False, status=SourceStatus.not_configured))

    if oemsecrets_configured:
        if oemsecrets_errors and len(oemsecrets_errors) == len(mpns):
            top_reports.append(SourceReport(
                name="oemsecrets", configured=True, status=SourceStatus.error,
                error="; ".join(sorted(set(oemsecrets_errors))[:3]),
            ))
        else:
            top_reports.append(SourceReport(
                name="oemsecrets", configured=True, status=SourceStatus.ok, offer_count=oemsecrets_offer_count,
            ))
    else:
        top_reports.append(SourceReport(name="oemsecrets", configured=False, status=SourceStatus.not_configured))

    configured_top_reports = [r for r in top_reports if r.configured]
    total_offers = sum(r.total_offers for r in results.values())
    all_sources_failed = bool(configured_top_reports) and all(
        r.status == SourceStatus.error for r in configured_top_reports
    )

    if not configured_top_reports:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "No live pricing sources configured. Add at least one API key to .env.",
                "sources": [r.model_dump() for r in top_reports],
            },
        )
    if all_sources_failed and total_offers == 0:
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"All {len(configured_top_reports)} configured live pricing source(s) failed for this BOM.",
                "all_sources_failed": True,
                "sources": [r.model_dump() for r in top_reports],
            },
        )

    return BomPriceResponse(
        results=results,
        total_mpns=len(mpns),
        sources_used=list(set(all_sources)),
        sources=top_reports,
        all_sources_failed=all_sources_failed,
    )


@router.post("/{mpn}/sync", response_model=SyncPricesResponse)
async def sync_component_prices(
    mpn: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch live prices for a component and update its DistributorOffer records in the DB.

    This upgrades static HuggingFace data with current real-time pricing.
    Only updates offers for distributors that already exist in the DB.
    Creates new offers for new distributors found in live data.
    """
    # Get component
    component = db.query(Component).filter(Component.mpn == mpn).first()
    if not component:
        raise HTTPException(status_code=404, detail=f"Component {mpn} not found in DB")

    # Fetch live prices via the shared helper (avoids internal HTTP call anti-pattern)
    try:
        raw_offers, sources_used, _reports = await _fetch_live_offers(mpn)
    except HTTPException as e:
        # Surface *why* rather than a bare "no offers" — e.detail is a
        # structured {"message": ..., "sources": [...]} dict for every
        # failure mode _fetch_live_offers raises (503/502/404).
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        return SyncPricesResponse(
            updated=0,
            message=detail.get("message", "No live offers available"),
        )

    merged = _deduplicate_offers(raw_offers)
    merged.sort(key=lambda o: o.get("price") or 9999)
    live_offers = [_to_live_offer(o) for o in merged]

    if not live_offers:
        return SyncPricesResponse(updated=0, message="No live offers found", sources=sources_used)

    updated = 0
    created = 0

    for live_offer in live_offers:
        if not live_offer.price:
            continue

        # Find existing distributor in DB by name
        distributor = (
            db.query(Distributor)
            .filter(Distributor.name.ilike(f"%{live_offer.distributor}%"))
            .first()
        )
        if not distributor:
            continue  # Only update known distributors

        # Find existing offer
        existing = (
            db.query(DistributorOffer)
            .filter(
                DistributorOffer.component_id == component.id,
                DistributorOffer.distributor_id == distributor.id,
            )
            .first()
        )

        if existing:
            existing.price = live_offer.price
            existing.stock = live_offer.stock
            existing.sku = live_offer.sku or existing.sku
            updated += 1
        else:
            new_offer = DistributorOffer(
                component_id=component.id,
                distributor_id=distributor.id,
                price=live_offer.price,
                stock=live_offer.stock,
                sku=live_offer.sku,
                currency=live_offer.currency,
            )
            db.add(new_offer)
            created += 1

    db.commit()
    return SyncPricesResponse(
        mpn=mpn,
        live_offers_found=len(live_offers),
        db_offers_updated=updated,
        db_offers_created=created,
        sources=sources_used,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _deduplicate_offers(offers: List[Dict]) -> List[Dict]:
    """Remove duplicate offers by (distributor, sku). Keep cheapest price."""
    seen: Dict[str, Dict] = {}
    for o in offers:
        dist = (o.get("distributor") or "").lower().strip()
        sku = str(o.get("sku") or "").strip()
        key = f"{dist}|{sku}" if sku else dist
        if key not in seen or (o.get("price") or 9999) < (seen[key].get("price") or 9999):
            seen[key] = o
    return list(seen.values())


def _to_live_offer(o: Dict) -> LiveOffer:
    return LiveOffer(
        distributor=o.get("distributor") or "Unknown",
        sku=str(o["sku"]) if o.get("sku") is not None else None,
        stock=int(o.get("stock") or 0),
        moq=int(o.get("moq") or 1),
        price=float(o.get("price") or 0),
        currency=o.get("currency") or "USD",
        is_authorized=bool(o.get("is_authorized", False)),
        price_breaks=o.get("price_breaks", []),
        lead_time_weeks=o.get("lead_time_weeks"),
        lifecycle_status=o.get("lifecycle_status"),
        datasheet_url=o.get("datasheet_url"),
        source=o.get("source") or "unknown",
    )
