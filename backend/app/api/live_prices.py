"""
Live pricing endpoints — real-time data from Nexar, DigiKey, OEMsecrets, TrustedParts.

These endpoints supplement (and eventually replace) the static HuggingFace dataset
with live API calls. They gracefully degrade: if a key is missing, that source is skipped.

Source priority:
  1. Nexar       — multi-distributor GraphQL (covers DigiKey, Mouser, Arrow, Farnell, LCSC in one call)
  2. OEMsecrets  — 40+ additional distributors in one call (free with approval)
  3. DigiKey     — official DK API for lifecycle_status + lead_time_weeks not in Nexar
  4. TrustedParts— authorized-distributor-only results, feeds is_authorized risk flag

Endpoints:
  GET /live-prices/{mpn}        — live pricing for a single part
  POST /live-prices/bom         — bulk BOM pricing (list of MPNs)
  GET /live-prices/{mpn}/sync   — fetch live prices and update DB for this component
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/live-prices", tags=["live-prices"])


# ── Schemas ────────────────────────────────────────────────────────────────────

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


class BomItem(BaseModel):
    mpn: str
    quantity: int = 1


class BomRequest(BaseModel):
    items: List[BomItem]


class BomPriceResponse(BaseModel):
    results: Dict[str, LivePriceResponse]
    total_mpns: int
    sources_used: List[str]


# ── Endpoints ──────────────────────────────────────────────────────────────────

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
    all_offers: List[Dict] = []
    sources_used: List[str] = []

    # ── Nexar (multi-distributor GraphQL) ──────────────────────────────────────
    if settings.NEXAR_CLIENT_ID and settings.NEXAR_CLIENT_SECRET:
        try:
            from app.core.clients.nexar_client import NexarClient
            client = NexarClient(settings.NEXAR_CLIENT_ID, settings.NEXAR_CLIENT_SECRET)
            part = await client.search_mpn(mpn)
            if part:
                offers = client.parse_offers(part)
                for o in offers:
                    o["source"] = "nexar"
                all_offers.extend(offers)
                sources_used.append("nexar")
        except Exception as e:
            print(f"[live_prices] Nexar error for {mpn}: {e}")

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
            all_offers.extend(offers)
            sources_used.append("oemsecrets")
        except Exception as e:
            print(f"[live_prices] OEMsecrets error for {mpn}: {e}")

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
            if product:
                offer = client.parse_offer(product)
                offer["source"] = "digikey"
                all_offers.append(offer)
                sources_used.append("digikey")
        except Exception as e:
            print(f"[live_prices] DigiKey error for {mpn}: {e}")

    # ── TrustedParts (authorized-only, feeds is_authorized risk flag) ────────────
    if settings.TRUSTEDPARTS_API_KEY:
        try:
            from app.core.clients.trustedparts_client import TrustedPartsClient
            client = TrustedPartsClient(settings.TRUSTEDPARTS_API_KEY)
            offers = await client.search_mpn(mpn)
            for o in offers:
                o["source"] = "trustedparts"
            all_offers.extend(offers)
            sources_used.append("trustedparts")
        except Exception as e:
            print(f"[live_prices] TrustedParts error for {mpn}: {e}")

    if not all_offers:
        if not sources_used:
            raise HTTPException(
                status_code=503,
                detail="No live pricing sources configured. Add at least one API key to .env.",
            )
        raise HTTPException(status_code=404, detail=f"No offers found for MPN: {mpn}")

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

    # ── Nexar bulk (preferred — one call for all MPNs) ─────────────────────────
    nexar_parts: Dict[str, Any] = {}
    if settings.NEXAR_CLIENT_ID and settings.NEXAR_CLIENT_SECRET:
        try:
            from app.core.clients.nexar_client import NexarClient
            client = NexarClient(settings.NEXAR_CLIENT_ID, settings.NEXAR_CLIENT_SECRET)
            bom_results = await client.search_bom(mpns)
            for item in bom_results:
                ref = item.get("reference") or ""
                part = item.get("part")
                if part and ref:
                    nexar_parts[ref] = part
            if nexar_parts:
                all_sources.append("nexar")
        except Exception as e:
            print(f"[live_prices] Nexar BOM error: {e}")

    for mpn in mpns:
        offers: List[Dict] = []
        sources: List[str] = []

        # Use Nexar bulk result
        if mpn in nexar_parts:
            from app.core.clients.nexar_client import NexarClient
            client = NexarClient(settings.NEXAR_CLIENT_ID, settings.NEXAR_CLIENT_SECRET)
            parsed = client.parse_offers(nexar_parts[mpn])
            for o in parsed:
                o["source"] = "nexar"
            offers.extend(parsed)
            sources.append("nexar")

        # Add OEMsecrets if available
        if settings.OEMSECRETS_API_KEY:
            try:
                from app.core.clients.oemsecrets_client import OEMSecretsClient
                oemc = OEMSecretsClient(settings.OEMSECRETS_API_KEY)
                oem_offers = await oemc.search_mpn(mpn)
                for o in oem_offers:
                    o["source"] = "oemsecrets"
                offers.extend(oem_offers)
                sources.append("oemsecrets")
            except Exception:
                pass

        merged = _deduplicate_offers(offers)
        merged.sort(key=lambda o: o.get("price") or 9999)
        all_sources.extend(sources)

        results[mpn] = LivePriceResponse(
            mpn=mpn,
            total_offers=len(merged),
            sources_used=list(set(sources)),
            offers=[_to_live_offer(o) for o in merged],
        )

    return BomPriceResponse(
        results=results,
        total_mpns=len(mpns),
        sources_used=list(set(all_sources)),
    )


@router.post("/{mpn}/sync")
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

    # Fetch live prices — pass through the authenticated user (internal call bypasses DI)
    live = await get_live_prices(mpn, current_user=current_user)
    if not live.offers:
        return {"updated": 0, "message": "No live offers found"}

    updated = 0
    created = 0

    for live_offer in live.offers:
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
    return {
        "mpn": mpn,
        "live_offers_found": len(live.offers),
        "db_offers_updated": updated,
        "db_offers_created": created,
        "sources": live.sources_used,
    }


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
