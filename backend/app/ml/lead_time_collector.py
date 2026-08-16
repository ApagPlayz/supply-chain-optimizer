"""
Weekly REAL lead-time snapshot collector (Route A, Track L — the data moat).

No free source publishes a *historical* per-part lead-time series. So we build
our own: poll the DigiKey + Mouser catalogs for every part in our DB, read the
REAL ``ManufacturerLeadWeeks`` / ``LeadTime`` each distributor is quoting today,
and append one timestamped row per (part, source) to a persistent CSV panel.
Run weekly and the panel accumulates into a genuine observed lead-time history
that the model can eventually train on — no synthetic formula anywhere.

Design guarantees
-----------------
* **Graceful no-op without keys.** If neither DIGIKEY nor MOUSER credentials are
  configured, the collector logs an honest message and returns without writing
  or fabricating anything.
* **Idempotent / deduped.** Re-running on the same calendar date does not create
  duplicate rows: existing rows for (snapshot_date, mpn, source) are overwritten,
  not appended. Safe to run from cron without guards.
* **Resumable.** Every attempt — hit *and* miss — is appended to
  ``collection_log.csv``. A re-run on the same snapshot_date skips MPNs that
  already reached a terminal outcome and retries only the errors, so a run that
  dies (or hits the daily quota) can be finished tomorrow without burning calls
  on parts already covered.
* **Quota-aware.** DigiKey's free tier is 1,000 calls/day with a 120/min burst
  ceiling. The collector reads the ``X-RateLimit-Remaining`` header off every
  response and stops when it gets within ``--reserve`` calls of the wall; it
  sleeps ``--sleep`` seconds between calls (default 0.65s ≈ 92/min) and honours
  ``Retry-After`` on a 429. When the header is *absent* (sandbox, proxy, or an
  error response that never reached DigiKey) the guard does not go blind: the
  run counts its own calls locally and stops at ``--daily-quota`` minus
  ``--reserve``, so ``DAILY_QUOTA`` is enforced either way.
* **Honest exit status.** A run that attempted work and collected nothing while
  hitting hard errors exits non-zero, so cron/CI can see the failure instead of
  reading a green tick over an empty panel. ``miss_rate`` is ``None`` — not a
  flattering ``0.0`` — when nothing was attempted at all.
* **Real-only.** Every stored value comes straight from a distributor API. Parts
  the API doesn't return, or returns without a lead time, produce a *log* row
  (so the miss rate is auditable) but never a fabricated panel row.
* **Match quality is recorded, not assumed.** DigiKey keyword search always
  returns its best guess, which is not necessarily our part. Each row carries
  ``match_type`` ∈ {exact, contains, fuzzy}; ``fuzzy`` rows are label noise and
  downstream training should filter to exact/contains.

Run:
    cd backend
    python -m app.ml.lead_time_collector                 # all parts, quota-guarded
    python -m app.ml.lead_time_collector --limit 50      # cap parts
    python -m app.ml.lead_time_collector --no-resume     # re-poll everything today
    python -m app.ml.lead_time_collector --dry-run       # show the plan, no calls
    python -m app.ml.lead_time_collector --sync-only     # no API calls; panel -> DB

Exit codes:
    0  the run did what it could (collected rows, or honestly no-opped: no keys,
       dry-run, nothing left to poll, or every attempt returned a real "the
       catalog has no lead time for this part" answer).
    1  the run is broken: it attempted at least one part, collected zero rows and
       hit at least one hard error. Also returned by ``--sync-only`` when there
       is no panel data to push into the DB.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import sqlalchemy as sa

logger = logging.getLogger(__name__)

# Persistent observed panel — one CSV, appended weekly. Lives under seeds/data
# alongside the other real datasets (this is the accumulating data moat).
PANEL_DIR = Path(__file__).resolve().parents[2] / "seeds" / "data" / "lead_time_panel"
PANEL_PATH = PANEL_DIR / "observed_lead_times.csv"
#: Every attempt, hit or miss. Drives resume + the honest miss-rate number.
LOG_PATH = PANEL_DIR / "collection_log.csv"

# ── Panel schema ─────────────────────────────────────────────────────────────
# LEGACY_COLUMNS are the original nine, unchanged in name, order and meaning, so
# the 75 rows collected on 2026-07-01 stay valid and every existing consumer
# (lead_time_model.panel_to_records) keeps working untouched.
LEGACY_COLUMNS = [
    "snapshot_date",     # YYYY-MM-DD the quote was observed
    "mpn",               # manufacturer part number (join key to components)
    "manufacturer",      # from our DB
    "category",          # from our DB (feature)
    "source",            # "digikey" | "mouser"
    "lead_time_weeks",   # REAL observed target
    "lifecycle_status",  # e.g. "Active", "Obsolete" (feature)
    "stock",             # units in stock at observation (feature)
    "unit_price",        # USD, legacy definition (ProductVariations[0], break 1)
]

# EXTENDED_COLUMNS are additive. Every one is read straight off the DigiKey
# product response — nothing derived, nothing invented. Rows collected before
# 2026-08-15 carry NaN here; that is a genuine "not observed", not a zero.
EXTENDED_COLUMNS = [
    # -- provenance / match quality --
    "match_type",                 # exact | contains | fuzzy
    "matched_mpn",                # ManufacturerProductNumber DigiKey returned
    "dk_part_number",             # DigiKeyProductNumber of the chosen variation
    "products_count",             # how many catalog hits the keyword returned
    "exact_match_count",          # len(ExactMatches) in the envelope
    "collected_at",               # UTC timestamp of the API call
    # -- identity --
    "dk_manufacturer",            # Manufacturer.Name (DigiKey's spelling)
    "dk_manufacturer_id",
    "dk_category",                # Category.Name
    "dk_subcategory",             # Category.ChildCategories[0].Name
    "dk_category_id",
    "series",                     # Series.Name
    "base_product",               # BaseProductNumber.Name
    "description",                # Description.ProductDescription
    # -- lifecycle / availability --
    "product_status_id",          # ProductStatus.Id
    "normally_stocking",          # NormallyStocking
    "discontinued",               # Discontinued
    "end_of_life",                # EndOfLife
    "ncnr",                       # Ncnr (non-cancellable / non-returnable)
    "back_order_not_allowed",     # BackOrderNotAllowed
    "date_last_buy_chance",       # DateLastBuyChance
    "quantity_available",         # QuantityAvailable (== legacy `stock`)
    "manufacturer_public_quantity",  # ManufacturerPublicQuantity (factory stock)
    "lead_time_weeks_raw",        # ManufacturerLeadWeeks exactly as returned
    # -- ordering / packaging (from the chosen variation) --
    "moq",                        # MinimumOrderQuantity
    "standard_package",           # StandardPackage
    "packaging",                  # PackageType.Name
    "variation_count",            # len(ProductVariations)
    "tariff_active",              # TariffActive
    "marketplace",                # MarketPlace
    "qty_available_for_package",  # QuantityAvailableforPackageType
    "max_qty_for_distribution",   # MaxQuantityForDistribution
    "digireel_fee",               # DigiReelFee
    # -- pricing --
    "dk_unit_price",              # top-level UnitPrice
    "price_break_count",          # len(StandardPricing) on the chosen variation
    "min_break_qty",
    "unit_price_min_break",
    "max_break_qty",
    "unit_price_max_break",
    # -- compliance / trade (Classifications) --
    "rohs_status",
    "reach_status",
    "moisture_sensitivity_level",
    "export_control_class",
    "htsus_code",                 # tariff code — real, and topical for sourcing
    # -- common parametrics (present across most categories) --
    "package_case",               # Parameters -> "Package / Case"
    "mounting_type",              # Parameters -> "Mounting Type"
    "parameter_count",            # len(Parameters)
]

PANEL_COLUMNS = LEGACY_COLUMNS + EXTENDED_COLUMNS

LOG_COLUMNS = [
    "snapshot_date", "mpn", "source", "status", "http_status",
    "match_type", "matched_mpn", "lead_time_weeks", "detail", "collected_at",
]

#: Log statuses that mean "don't spend another API call on this part today".
TERMINAL_STATUSES = {"ok", "no_lead_time", "no_match"}

# DigiKey free tier. Verified 2026-08-15 from the live X-RateLimit-Limit header.
DAILY_QUOTA = 1000
DEFAULT_RESERVE = 25          # stop this many calls short of the wall
DEFAULT_SLEEP = 0.65          # ≈92 calls/min, under the 120/min burst ceiling
FLUSH_EVERY = 25              # persist partial progress this often


# ── helpers ──────────────────────────────────────────────────────────────────

def _norm(s: Optional[str]) -> str:
    """Uppercase, strip everything that isn't alphanumeric (MPN comparison)."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _classify_match(query_mpn: str, returned_mpn: Optional[str]) -> str:
    q, r = _norm(query_mpn), _norm(returned_mpn)
    if not r:
        return "fuzzy"
    if q == r:
        return "exact"
    if q and (q in r or r in q):
        return "contains"
    return "fuzzy"


def _pick_product(mpn: str, envelope: Dict[str, Any]) -> Tuple[Optional[Dict], str]:
    """
    Choose which returned product is *our* part, preferring DigiKey's own
    ExactMatches, then a normalized MPN equality, then substring, then the
    top-ranked hit (flagged ``fuzzy`` so training can drop it).
    """
    candidates: List[Dict[str, Any]] = list(envelope.get("exact_matches") or [])
    candidates += list(envelope.get("products") or [])
    if not candidates:
        return None, "none"

    best: Optional[Dict[str, Any]] = None
    best_rank = 99
    ranks = {"exact": 0, "contains": 1, "fuzzy": 2}
    for prod in candidates:
        mt = _classify_match(mpn, prod.get("ManufacturerProductNumber")
                             or prod.get("ManufacturerPartNumber"))
        if ranks[mt] < best_rank:
            best, best_rank = prod, ranks[mt]
        if best_rank == 0:
            break
    match_type = {0: "exact", 1: "contains", 2: "fuzzy"}[best_rank]
    return best, match_type


def _pick_variation(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    The variation a buyer would actually order: lowest MinimumOrderQuantity,
    tie-broken by most stock. Empty dict when the product has no variations.
    """
    variations = product.get("ProductVariations") or []
    if not variations:
        return {}
    def key(v: Dict[str, Any]):
        moq = v.get("MinimumOrderQuantity")
        moq = moq if isinstance(moq, (int, float)) else 10 ** 9
        qty = v.get("QuantityAvailableforPackageType") or 0
        return (moq, -qty)
    return sorted(variations, key=key)[0]


def _param(product: Dict[str, Any], name: str) -> Optional[str]:
    for p in product.get("Parameters") or []:
        if p.get("ParameterText") == name:
            val = p.get("ValueText")
            return None if val in (None, "", "-") else val
    return None


def _digikey_extended(mpn: str, product: Dict[str, Any], match_type: str,
                      envelope: Dict[str, Any], collected_at: str) -> Dict[str, Any]:
    """Flatten the extra REAL fields off a DigiKey product response."""
    var = _pick_variation(product)
    pricing = var.get("StandardPricing") or []
    breaks = sorted(
        [(t.get("BreakQuantity"), t.get("UnitPrice")) for t in pricing
         if t.get("BreakQuantity") is not None and t.get("UnitPrice") is not None],
        key=lambda t: t[0],
    )
    category = product.get("Category") or {}
    children = category.get("ChildCategories") or []
    classifications = product.get("Classifications") or {}
    status = product.get("ProductStatus") or {}

    def _name(node: Any) -> Optional[str]:
        if isinstance(node, dict):
            val = node.get("Name")
            return None if val in (None, "", "-") else val
        return None

    return {
        "match_type": match_type,
        "matched_mpn": product.get("ManufacturerProductNumber")
                       or product.get("ManufacturerPartNumber"),
        "dk_part_number": var.get("DigiKeyProductNumber"),
        "products_count": envelope.get("products_count"),
        "exact_match_count": len(envelope.get("exact_matches") or []),
        "collected_at": collected_at,

        "dk_manufacturer": _name(product.get("Manufacturer")),
        "dk_manufacturer_id": (product.get("Manufacturer") or {}).get("Id"),
        "dk_category": _name(category),
        "dk_subcategory": _name(children[0]) if children else None,
        "dk_category_id": category.get("CategoryId"),
        "series": _name(product.get("Series")),
        "base_product": _name(product.get("BaseProductNumber")),
        "description": (product.get("Description") or {}).get("ProductDescription"),

        "product_status_id": status.get("Id"),
        "normally_stocking": product.get("NormallyStocking"),
        "discontinued": product.get("Discontinued"),
        "end_of_life": product.get("EndOfLife"),
        "ncnr": product.get("Ncnr"),
        "back_order_not_allowed": product.get("BackOrderNotAllowed"),
        "date_last_buy_chance": product.get("DateLastBuyChance"),
        "quantity_available": product.get("QuantityAvailable"),
        "manufacturer_public_quantity": product.get("ManufacturerPublicQuantity"),
        "lead_time_weeks_raw": product.get("ManufacturerLeadWeeks"),

        "moq": var.get("MinimumOrderQuantity"),
        "standard_package": var.get("StandardPackage"),
        "packaging": _name(var.get("PackageType")),
        "variation_count": len(product.get("ProductVariations") or []),
        "tariff_active": var.get("TariffActive"),
        "marketplace": var.get("MarketPlace"),
        "qty_available_for_package": var.get("QuantityAvailableforPackageType"),
        "max_qty_for_distribution": var.get("MaxQuantityForDistribution"),
        "digireel_fee": var.get("DigiReelFee"),

        "dk_unit_price": product.get("UnitPrice"),
        "price_break_count": len(breaks),
        "min_break_qty": breaks[0][0] if breaks else None,
        "unit_price_min_break": breaks[0][1] if breaks else None,
        "max_break_qty": breaks[-1][0] if breaks else None,
        "unit_price_max_break": breaks[-1][1] if breaks else None,

        "rohs_status": classifications.get("RohsStatus"),
        "reach_status": classifications.get("ReachStatus"),
        "moisture_sensitivity_level": classifications.get("MoistureSensitivityLevel"),
        "export_control_class": classifications.get("ExportControlClassNumber"),
        "htsus_code": classifications.get("HtsusCode"),

        "package_case": _param(product, "Package / Case"),
        "mounting_type": _param(product, "Mounting Type"),
        "parameter_count": len(product.get("Parameters") or []),
    }


def _load_log() -> pd.DataFrame:
    if LOG_PATH.exists():
        try:
            return pd.read_csv(LOG_PATH)
        except Exception:  # noqa: BLE001 — a corrupt log must not block collection
            logger.warning("collection log unreadable — starting a fresh one")
    return pd.DataFrame(columns=LOG_COLUMNS)


def _already_done(log: pd.DataFrame, snapshot_date: str, source: str) -> Set[str]:
    """MPNs that already reached a terminal outcome for this snapshot + source."""
    if log.empty:
        return set()
    m = (log["snapshot_date"].astype(str) == snapshot_date) & \
        (log["source"].astype(str) == source) & \
        (log["status"].astype(str).isin(TERMINAL_STATUSES))
    return set(log.loc[m, "mpn"].astype(str))


# ── collection ───────────────────────────────────────────────────────────────

class _Budget:
    """
    Tracks the DigiKey daily quota.

    Preferred signal is the ``X-RateLimit-Remaining`` header, which is the
    authoritative server-side counter. But that header is only present on a
    response that actually reached DigiKey — a DNS failure, a proxy, a timeout
    or the sandbox host all leave it ``None``, and a guard that only reads the
    header is therefore inert exactly when a run is misbehaving and burning
    calls. So the budget also counts its own calls and enforces ``daily_quota``
    (``DAILY_QUOTA`` by default) locally whenever the header has never been seen.
    """

    def __init__(self, reserve: int, max_calls: Optional[int],
                 daily_quota: Optional[int] = DAILY_QUOTA):
        self.reserve = reserve
        self.max_calls = max_calls
        self.daily_quota = daily_quota
        self.calls = 0
        self.remaining: Optional[int] = None
        self.limit: Optional[int] = None
        self.exhausted = False

    @property
    def local_ceiling(self) -> Optional[int]:
        """Calls this run may make before the local (header-less) guard trips."""
        if self.daily_quota is None:
            return None
        return max(self.daily_quota - self.reserve, 0)

    def observe(self, envelope: Dict[str, Any]) -> None:
        self.calls += 1
        if envelope.get("rate_limit_remaining") is not None:
            self.remaining = envelope["rate_limit_remaining"]
        if envelope.get("rate_limit_limit") is not None:
            self.limit = envelope["rate_limit_limit"]
            # Trust the server's own stated ceiling over our compiled-in guess.
            self.daily_quota = envelope["rate_limit_limit"]

    def should_stop(self) -> Optional[str]:
        if self.max_calls is not None and self.calls >= self.max_calls:
            return f"--max-calls={self.max_calls} reached"
        if self.remaining is not None:
            if self.remaining <= self.reserve:
                return f"daily quota nearly exhausted (remaining={self.remaining})"
            return None
        # No rate-limit header has ever come back — fall back to our own counter
        # so DAILY_QUOTA is a real budget rather than an unused constant.
        ceiling = self.local_ceiling
        if ceiling is not None and self.calls >= ceiling:
            return (f"local call budget reached: {self.calls} calls made, "
                    f"quota={self.daily_quota} reserve={self.reserve}, "
                    f"no x-ratelimit-remaining header seen")
        return None


async def _collect_async(
    limit: Optional[int],
    resume: bool,
    sleep_s: float,
    reserve: int,
    max_calls: Optional[int],
    snapshot_date: str,
    dry_run: bool,
    daily_quota: Optional[int] = DAILY_QUOTA,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Poll DigiKey (and Mouser, when configured) for each part MPN in the DB.

    Returns ``(new_panel_rows, new_log_rows, stats)``. Never fabricates data.
    """
    from app.core.config import settings

    have_digikey = bool(settings.DIGIKEY_CLIENT_ID and settings.DIGIKEY_CLIENT_SECRET)
    have_mouser = bool(getattr(settings, "MOUSER_API_KEY", ""))

    stats: Dict[str, Any] = {
        "attempted": 0, "hits": 0, "no_lead_time": 0, "no_match": 0, "errors": 0,
        "skipped_resume": 0, "api_calls": 0, "stopped_early": None,
        "quota_remaining": None, "quota_source": None,
        "match_types": {}, "rows_written": 0,
    }

    if not have_digikey and not have_mouser:
        logger.warning(
            "lead-time collector: no DigiKey or Mouser credentials configured — "
            "nothing to collect. No rows written, no synthetic data generated."
        )
        return (pd.DataFrame(columns=PANEL_COLUMNS),
                pd.DataFrame(columns=LOG_COLUMNS), stats)

    from app.core.database import engine
    from app.models.component import Component
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        components = [
            {"mpn": c.mpn, "manufacturer": c.manufacturer or "",
             "category": c.category or "Unknown"}
            for c in db.query(Component).order_by(Component.id).all()
            if c.mpn
        ]

    # De-dup MPNs — one API call per distinct part, not per DB row.
    seen: Set[str] = set()
    unique: List[Dict[str, str]] = []
    for c in components:
        if c["mpn"] not in seen:
            seen.add(c["mpn"])
            unique.append(c)
    components = unique

    log = _load_log()
    done = _already_done(log, snapshot_date, "digikey") if resume else set()
    todo = [c for c in components if c["mpn"] not in done]
    stats["skipped_resume"] = len(components) - len(todo)
    if limit:
        todo = todo[:limit]

    logger.info(
        "lead-time collector: %d parts in DB, %d already done for %s, %d to poll "
        "(DigiKey=%s, Mouser=%s)",
        len(components), stats["skipped_resume"], snapshot_date, len(todo),
        have_digikey, have_mouser,
    )
    if dry_run:
        stats["stopped_early"] = "dry-run"
        return (pd.DataFrame(columns=PANEL_COLUMNS),
                pd.DataFrame(columns=LOG_COLUMNS), stats)

    rows: List[dict] = []
    log_rows: List[dict] = []
    budget = _Budget(reserve, max_calls, daily_quota)

    if have_digikey:
        import httpx
        from app.core.clients.digikey_client import DigiKeyClient

        digikey = DigiKeyClient(
            settings.DIGIKEY_CLIENT_ID,
            settings.DIGIKEY_CLIENT_SECRET,
            sandbox=settings.DIGIKEY_SANDBOX,
        )
        async with httpx.AsyncClient(timeout=30) as http:
            for i, comp in enumerate(todo, 1):
                stop = budget.should_stop()
                if stop:
                    stats["stopped_early"] = stop
                    logger.warning("stopping early: %s", stop)
                    break

                mpn = comp["mpn"]
                collected_at = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
                env = await digikey.search_mpn_envelope(mpn, limit=5, client=http)
                budget.observe(env)
                stats["attempted"] += 1

                # 429 → honour Retry-After once, then move on (logged as error).
                if env.get("status_code") == 429:
                    wait = env.get("retry_after") or 60
                    logger.warning("429 from DigiKey — sleeping %ss", wait)
                    await asyncio.sleep(min(wait, 120))
                    env = await digikey.search_mpn_envelope(mpn, limit=5, client=http)
                    budget.observe(env)

                if not env.get("ok"):
                    stats["errors"] += 1
                    log_rows.append(_log_row(snapshot_date, mpn, "digikey", "error",
                                             env.get("status_code"), None, None, None,
                                             (env.get("error") or "")[:200], collected_at))
                else:
                    product, match_type = _pick_product(mpn, env)
                    if product is None:
                        stats["no_match"] += 1
                        log_rows.append(_log_row(snapshot_date, mpn, "digikey", "no_match",
                                                 env.get("status_code"), None, None, None,
                                                 "catalog returned 0 products", collected_at))
                    else:
                        offer = digikey.parse_offer(product)   # legacy fields, unchanged
                        lead_weeks = _coerce_weeks(offer.get("lead_time_weeks"))
                        if lead_weeks is None:
                            stats["no_lead_time"] += 1
                            log_rows.append(_log_row(
                                snapshot_date, mpn, "digikey", "no_lead_time",
                                env.get("status_code"), match_type,
                                product.get("ManufacturerProductNumber"), None,
                                "product found, ManufacturerLeadWeeks empty", collected_at))
                        else:
                            row = {
                                "snapshot_date": snapshot_date,
                                "mpn": mpn,
                                "manufacturer": comp["manufacturer"],
                                "category": comp["category"],
                                "source": "digikey",
                                "lead_time_weeks": lead_weeks,
                                "lifecycle_status": offer.get("lifecycle_status"),
                                "stock": offer.get("stock", 0),
                                "unit_price": offer.get("price"),
                            }
                            row.update(_digikey_extended(mpn, product, match_type,
                                                         env, collected_at))
                            rows.append(row)
                            stats["hits"] += 1
                            stats["match_types"][match_type] = \
                                stats["match_types"].get(match_type, 0) + 1
                            log_rows.append(_log_row(
                                snapshot_date, mpn, "digikey", "ok",
                                env.get("status_code"), match_type,
                                row["matched_mpn"], lead_weeks, "", collected_at))

                if i % FLUSH_EVERY == 0:
                    _flush(rows, log_rows, stats)
                    logger.info(
                        "  … %d/%d polled | hits=%d no_lt=%d no_match=%d err=%d | quota left=%s",
                        i, len(todo), stats["hits"], stats["no_lead_time"],
                        stats["no_match"], stats["errors"], budget.remaining,
                    )
                await asyncio.sleep(sleep_s)

    if have_mouser:
        from app.core.clients.mouser_client import MouserClient
        mouser = MouserClient(settings.MOUSER_API_KEY)
        for comp in todo:
            part = await mouser.search_mpn(comp["mpn"])
            if not part:
                continue
            offer = mouser.parse_offer(part)
            lead_weeks = _coerce_weeks(offer.get("lead_time_weeks"))
            if lead_weeks is None:
                continue
            rows.append({
                "snapshot_date": snapshot_date, "mpn": comp["mpn"],
                "manufacturer": comp["manufacturer"], "category": comp["category"],
                "source": "mouser", "lead_time_weeks": lead_weeks,
                "lifecycle_status": offer.get("lifecycle_status"),
                "stock": offer.get("stock", 0), "unit_price": offer.get("price"),
            })
            await asyncio.sleep(sleep_s)

    stats["api_calls"] = budget.calls
    stats["quota_remaining"] = budget.remaining
    stats["quota_source"] = "header" if budget.remaining is not None else (
        "local_counter" if budget.calls else None
    )
    return (pd.DataFrame(rows, columns=PANEL_COLUMNS),
            pd.DataFrame(log_rows, columns=LOG_COLUMNS), stats)


def _coerce_weeks(raw: Any) -> Optional[float]:
    """
    DigiKey returns ManufacturerLeadWeeks as a STRING ("6", "30 Weeks", "").
    Pull the leading number; return None when there is no real number to read.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None
    m = re.search(r"\d+(?:\.\d+)?", str(raw))
    if not m:
        return None
    val = float(m.group())
    return val if val > 0 else None


def _log_row(snapshot_date, mpn, source, status, http_status, match_type,
             matched_mpn, lead_weeks, detail, collected_at) -> dict:
    return {
        "snapshot_date": snapshot_date, "mpn": mpn, "source": source,
        "status": status, "http_status": http_status, "match_type": match_type,
        "matched_mpn": matched_mpn, "lead_time_weeks": lead_weeks,
        "detail": detail, "collected_at": collected_at,
    }


def _flush(rows: List[dict], log_rows: List[dict],
           stats: Optional[Dict[str, Any]] = None) -> None:
    """
    Persist partial progress so a crash or a quota stop loses nothing, and keep
    a running total — the caller can no longer count rows off the in-memory
    list, because flushing empties it.
    """
    if rows:
        _persist_panel(pd.DataFrame(rows, columns=PANEL_COLUMNS))
        if stats is not None:
            stats["rows_written"] = stats.get("rows_written", 0) + len(rows)
        rows.clear()
    if log_rows:
        _persist_log(pd.DataFrame(log_rows, columns=LOG_COLUMNS))
        log_rows.clear()


def _persist_panel(new_rows: pd.DataFrame) -> int:
    """
    Merge new rows into the panel, deduping on (snapshot_date, mpn, source) —
    the newest observation wins. Old rows keep their values and get NaN for the
    columns that did not exist when they were collected.
    """
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    if PANEL_PATH.exists():
        existing = pd.read_csv(PANEL_PATH)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows
    combined = combined.drop_duplicates(
        subset=["snapshot_date", "mpn", "source"], keep="last"
    ).reset_index(drop=True)
    # Stable column order: legacy nine first, then extended, then anything else.
    ordered = [c for c in PANEL_COLUMNS if c in combined.columns]
    ordered += [c for c in combined.columns if c not in ordered]
    combined = combined[ordered]

    # Concatenating a partial batch widens int columns to float, which would
    # rewrite every pre-existing `8` as `8.0` and churn the whole file in git
    # for no reason. Put counts back to a nullable integer when every value in
    # them really is integral. Purely cosmetic — no value changes.
    _MONEY = {"unit_price", "dk_unit_price", "unit_price_min_break",
              "unit_price_max_break", "digireel_fee"}
    for col in combined.columns:
        if col in _MONEY:
            continue                       # a price is a float even when it is 5.00
        s = pd.to_numeric(combined[col], errors="coerce")
        if s.notna().sum() == 0 or s.isna().sum() != combined[col].isna().sum():
            continue                       # not a numeric column
        nn = s.dropna()
        if len(nn) and (nn % 1 == 0).all() and nn.abs().max() < 2 ** 62:
            combined[col] = s.astype("Int64")

    combined.to_csv(PANEL_PATH, index=False)
    return len(combined)


def _persist_log(new_log: pd.DataFrame) -> int:
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists():
        existing = pd.read_csv(LOG_PATH)
        combined = pd.concat([existing, new_log], ignore_index=True)
    else:
        combined = new_log
    combined = combined.drop_duplicates(
        subset=["snapshot_date", "mpn", "source"], keep="last"
    ).reset_index(drop=True)
    combined.to_csv(LOG_PATH, index=False)
    return len(combined)


def collect_snapshot(
    limit: Optional[int] = None,
    *,
    resume: bool = True,
    sleep_s: float = DEFAULT_SLEEP,
    reserve: int = DEFAULT_RESERVE,
    max_calls: Optional[int] = None,
    snapshot_date: Optional[str] = None,
    dry_run: bool = False,
    sync_db: bool = True,
    daily_quota: Optional[int] = DAILY_QUOTA,
) -> dict:
    """
    Collect one lead-time snapshot and persist it to the panel CSV.

    Returns a status dict::

        {"status": "no_keys" | "collected" | "no_data",
         "rows_added": int, "panel_total": int, "panel_path": str,
         "attempted": int, "hits": int, "miss_rate": float | None, ...}

    ``miss_rate`` is ``None``, never ``0.0``, when ``attempted == 0`` — a run
    that tried nothing has no miss rate to report. Callers must handle ``None``.

    Safe to call with no API keys — it no-ops honestly.
    """
    snapshot_date = snapshot_date or _dt.date.today().isoformat()
    t0 = time.time()
    new_rows, new_log, stats = asyncio.run(_collect_async(
        limit, resume, sleep_s, reserve, max_calls, snapshot_date, dry_run,
        daily_quota,
    ))

    if not new_log.empty:
        _persist_log(new_log)

    attempted = stats["attempted"]
    misses = stats["no_match"] + stats["no_lead_time"] + stats["errors"]
    # A run that attempted nothing has no miss rate — it has no *rate* at all.
    # Reporting 0.0 there let a no-op (no keys, dry-run, everything already done,
    # or a crash before the first call) publish the single best number the metric
    # can take. None says "undefined", which is the truth.
    miss_rate: Optional[float] = round(misses / attempted, 4) if attempted else None

    # Rows already flushed mid-run are NOT in `new_rows` any more — count both.
    rows_added = int(stats.get("rows_written", 0)) + int(len(new_rows))
    panel_total = _persist_panel(new_rows) if not new_rows.empty else _panel_len()

    if rows_added == 0:
        from app.core.config import settings
        no_keys = not (settings.DIGIKEY_CLIENT_ID or getattr(settings, "MOUSER_API_KEY", ""))
        result: Dict[str, Any] = {
            "status": "no_keys" if no_keys else "no_data", "rows_added": 0,
            "panel_total": panel_total, "panel_path": str(PANEL_PATH),
        }
    else:
        result = {
            "status": "collected", "rows_added": rows_added,
            "panel_total": int(panel_total), "panel_path": str(PANEL_PATH),
        }
        logger.info("wrote %d new rows; panel now holds %d observations at %s",
                    rows_added, panel_total, PANEL_PATH)

    result.update({
        "snapshot_date": snapshot_date,
        "attempted": attempted,
        "hits": stats["hits"],
        "no_match": stats["no_match"],
        "no_lead_time": stats["no_lead_time"],
        "errors": stats["errors"],
        "miss_rate": miss_rate,
        "match_types": stats["match_types"],
        "skipped_resume": stats["skipped_resume"],
        "api_calls": stats["api_calls"],
        "quota_remaining": stats["quota_remaining"],
        "quota_source": stats["quota_source"],
        "stopped_early": stats["stopped_early"],
        "elapsed_s": round(time.time() - t0, 1),
        "log_path": str(LOG_PATH),
    })

    # Push the catalog attributes into the DB in the SAME run, so the features
    # the panel trains on are actually available at serving time.
    if sync_db and not dry_run and result["status"] == "collected":
        try:
            result["db_sync"] = sync_db_from_panel()
            logger.info("db sync: %s", result["db_sync"].get("status"))
        except Exception as e:  # noqa: BLE001 — a DB problem must not lose the CSV
            logger.warning("db sync failed (panel is still safely written): %s", e)
            result["db_sync"] = {"status": "error", "detail": str(e)}
    return result


# ── DB sync ──────────────────────────────────────────────────────────────────
#
# The panel is the training corpus; the DB is what the API serves from. Anything
# the model learns from must also be readable at prediction time, or the feature
# is dead weight. These are the panel columns that map onto ORM columns added in
# migration 0006 — nothing is derived, and a missing API value stays NULL.

#: panel column -> Component attribute
_COMPONENT_SYNC = {
    "lifecycle_status": "lifecycle_status",
    "normally_stocking": "normally_stocked",
    "discontinued": "discontinued",
    "end_of_life": "end_of_life",
    "dk_category": "digikey_category",
    "dk_subcategory": "digikey_subcategory",
    "lead_time_weeks": "observed_lead_time_weeks",
    # migration 0007 — see app/models/component.py for why these are all
    # part-level even though some look offer-shaped.
    "parameter_count": "parameter_count",
    "package_case": "package_case",
    "htsus_code": "htsus_code",
    "rohs_status": "rohs_status",
    "dk_unit_price": "digikey_unit_price",
    "max_break_qty": "max_break_qty",
    "price_break_count": "price_break_count",
}
#: panel column -> DistributorOffer attribute (DigiKey offers only)
_OFFER_SYNC = {
    "standard_package": "standard_pack",
    "packaging": "packaging",
}


def _clean(value: Any) -> Any:
    """CSV/NaN -> None; numpy scalars -> python; bool-ish strings -> bool."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        return s
    if hasattr(value, "item"):
        return value.item()
    return value


def _coerce_for_column(model: Any, attr: str, value: Any) -> Any:
    """Reshape a cleaned panel value to match its destination column type.

    Pandas reads any numeric CSV column that contains at least one blank as
    float64, so an Integer-column value like ``parameter_count`` arrives as
    ``18.0`` rather than ``18``. Cast whole floats destined for an Integer
    column to int; leave everything else (including None) untouched. This
    only reshapes a value that's already present — it never invents one.
    """
    if value is None:
        return None
    col_type = model.__table__.columns[attr].type
    if isinstance(col_type, sa.Integer) and isinstance(value, float):
        return int(value)
    return value


def sync_db_from_panel(snapshot_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Push the DigiKey catalog attributes from the panel into the DB so the model
    can SERVE the features it TRAINS on (migration 0006 columns).

    Only ``match_type`` ∈ {exact, contains} rows are synced — a fuzzy keyword hit
    is a different part, and writing its lifecycle status onto our component
    would be fabricated data. Returns per-column fill counts.
    """
    from app.core.database import engine
    from app.models.component import Component, DistributorOffer
    from app.models.distributor import Distributor
    from sqlalchemy.orm import Session

    if not PANEL_PATH.exists():
        return {"status": "no_panel"}

    panel = pd.read_csv(PANEL_PATH)
    panel = panel[panel["source"].astype(str) == "digikey"]
    if "match_type" in panel.columns:
        panel = panel[panel["match_type"].isin(["exact", "contains"])]
    if snapshot_date:
        panel = panel[panel["snapshot_date"].astype(str) == snapshot_date]
    if panel.empty:
        return {"status": "no_rows"}

    # Most recent observation per MPN wins.
    panel = panel.sort_values("snapshot_date").drop_duplicates("mpn", keep="last")
    by_mpn = {str(r["mpn"]): r for _, r in panel.iterrows()}

    filled: Dict[str, int] = {a: 0 for a in list(_COMPONENT_SYNC.values()) + list(_OFFER_SYNC.values())}
    filled["lead_time_observed_at"] = 0
    filled["moq"] = 0
    stats: Dict[str, Any] = {
        "components_total": 0, "components_seen": 0, "components_updated": 0,
        "offers_seen": 0, "offers_updated": 0, "offers_missing": 0,
        "offers_variation_unmatched": 0,
    }

    with Session(engine) as db:
        dk = db.query(Distributor).filter(Distributor.name.ilike("digikey")).first()
        dk_id = dk.id if dk else None

        for comp in db.query(Component).all():
            stats["components_total"] += 1
            row = by_mpn.get(str(comp.mpn))
            if row is None:
                continue
            stats["components_seen"] += 1
            touched = False
            for panel_col, attr in _COMPONENT_SYNC.items():
                val = _coerce_for_column(Component, attr, _clean(row.get(panel_col)))
                if val is not None:
                    setattr(comp, attr, val)
                    filled[attr] += 1
                    touched = True
            if _clean(row.get("lead_time_weeks")) is not None:
                snap = _clean(row.get("snapshot_date"))
                if snap:
                    comp.lead_time_observed_at = _dt.date.fromisoformat(str(snap)[:10])
                    filled["lead_time_observed_at"] += 1
            if touched:
                stats["components_updated"] += 1

            if dk_id is None:
                continue
            offers = db.query(DistributorOffer).filter(
                DistributorOffer.component_id == comp.id,
                DistributorOffer.distributor_id == dk_id,
            ).all()
            if not offers:
                stats["offers_missing"] += 1
                continue
            # Idempotent: clear what a previous sync wrote before re-deriving,
            # so a corrected match rule can't leave stale values behind.
            for offer in offers:
                offer.standard_pack = None
                offer.packaging = None
            # A DigiKey part usually has several offers — one per packaging
            # variation (Cut Tape / Tape & Reel / Digi-Reel), each with its own
            # DigiKeyProductNumber in `sku`. The panel records the ONE variation
            # we read (`dk_part_number`), so only that offer legitimately gets
            # this packaging. Writing it onto the part's other variations would
            # be inventing an observation we never made, so they stay NULL.
            observed_sku = str(_clean(row.get("dk_part_number")) or "").strip().upper()
            for offer in offers:
                stats["offers_seen"] += 1
                if not observed_sku or str(offer.sku or "").strip().upper() != observed_sku:
                    stats["offers_variation_unmatched"] += 1
                    continue
                hit = False
                for panel_col, attr in _OFFER_SYNC.items():
                    val = _coerce_for_column(DistributorOffer, attr, _clean(row.get(panel_col)))
                    if val is not None:
                        setattr(offer, attr, val)
                        filled[attr] += 1
                        hit = True
                # moq already exists on the model — only FILL holes, never
                # overwrite an existing figure with a different vintage.
                moq = _clean(row.get("moq"))
                if moq is not None and not offer.moq:
                    offer.moq = int(moq)
                    filled["moq"] += 1
                    hit = True
                if hit:
                    stats["offers_updated"] += 1

        db.commit()

    # Fill rate is reported against the right denominator for each scope:
    # part-level columns over all components in the DB, offer-level columns over
    # the DigiKey offer rows actually visited.
    n_comp = stats["components_total"] or 1
    n_offer = stats["offers_seen"] or 1
    offer_attrs = set(_OFFER_SYNC.values()) | {"moq"}
    stats["fill_rate"] = {
        k: round(v / (n_offer if k in offer_attrs else n_comp), 4)
        for k, v in filled.items()
    }
    stats["filled_counts"] = filled
    stats["status"] = "synced"
    return stats


def _panel_len() -> int:
    if PANEL_PATH.exists():
        try:
            return int(len(pd.read_csv(PANEL_PATH)))
        except Exception:  # noqa: BLE001
            return 0
    return 0


EXIT_OK = 0
EXIT_FAILED = 1


def run_failure_reason(result: Dict[str, Any]) -> Optional[str]:
    """
    Decide whether a finished run should be reported as a FAILURE.

    "Fully failed" means: the run actually tried to collect (``attempted > 0``),
    came away with nothing (``hits == 0``), and at least one attempt blew up with
    a hard error rather than a real answer from the API. That is the shape of a
    broken run — expired credentials, no network, DigiKey down — and cron needs
    a non-zero exit to notice it.

    Deliberately NOT failures:

    * ``attempted == 0`` — a no-key no-op, a dry-run, or "everything for today is
      already collected". Nothing was tried, so nothing failed.
    * ``hits > 0`` — a partial success is still a success; some parts always miss.
    * ``hits == 0`` with ``errors == 0`` — every call worked, the catalog simply
      had no lead time for any of the parts polled. That is a real (if useless)
      answer, so it warns loudly instead of exiting non-zero.
    """
    attempted = int(result.get("attempted") or 0)
    hits = int(result.get("hits") or 0)
    errors = int(result.get("errors") or 0)
    if attempted > 0 and hits == 0 and errors > 0:
        return (f"collected nothing: {attempted} parts attempted, 0 rows, "
                f"{errors} hard errors "
                f"(no_match={result.get('no_match')}, "
                f"no_lead_time={result.get('no_lead_time')})")
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Collect a real lead-time snapshot.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap number of parts polled this run.")
    p.add_argument("--no-resume", dest="resume", action="store_false",
                   help="Re-poll parts already collected for today's snapshot.")
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                   help=f"Seconds between API calls (default {DEFAULT_SLEEP}).")
    p.add_argument("--reserve", type=int, default=DEFAULT_RESERVE,
                   help="Stop this many calls short of the daily quota.")
    p.add_argument("--daily-quota", type=int, default=DAILY_QUOTA,
                   help=(f"Daily API call budget (default {DAILY_QUOTA}). Enforced "
                         "from a local counter whenever the x-ratelimit-remaining "
                         "response header is absent. 0 disables the local guard."))
    p.add_argument("--max-calls", type=int, default=None,
                   help="Hard cap on API calls this run.")
    p.add_argument("--snapshot-date", default=None,
                   help="Override the snapshot date (YYYY-MM-DD).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report the plan without making any API calls.")
    p.add_argument("--no-sync-db", dest="sync_db", action="store_false",
                   help="Skip writing the catalog attributes back into the DB.")
    p.add_argument("--sync-only", action="store_true",
                   help="Make no API calls; just push the existing panel into the DB.")
    args = p.parse_args()

    if args.sync_only:
        sync = sync_db_from_panel()
        logger.info("db sync result: %s", sync)
        if sync.get("status") != "synced":
            logger.error("sync-only produced no DB writes (status=%s) — "
                         "there is no panel data to restore from.",
                         sync.get("status"))
            sys.exit(EXIT_FAILED)
        sys.exit(EXIT_OK)

    result = collect_snapshot(
        limit=args.limit, resume=args.resume, sleep_s=args.sleep,
        reserve=args.reserve, max_calls=args.max_calls,
        snapshot_date=args.snapshot_date, dry_run=args.dry_run,
        sync_db=args.sync_db, daily_quota=args.daily_quota or None,
    )
    logger.info("collector result: %s", result)

    failure = run_failure_reason(result)
    if failure:
        logger.error("lead-time collector FAILED — %s", failure)
        sys.exit(EXIT_FAILED)
    if int(result.get("attempted") or 0) > 0 and int(result.get("hits") or 0) == 0:
        logger.warning(
            "lead-time collector collected 0 rows, but every API call succeeded "
            "— the catalog genuinely had no lead time for the parts polled. "
            "Exiting 0."
        )
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
