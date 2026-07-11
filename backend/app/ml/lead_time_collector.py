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
  or fabricating anything. (Keys are absent right now — this is the tested path.)
* **Idempotent / deduped.** Re-running on the same calendar date does not create
  duplicate rows: existing rows for (snapshot_date, mpn, source) are overwritten,
  not appended. Safe to run from cron without guards.
* **Real-only.** Every stored value comes straight from a distributor API. Parts
  the API doesn't return, or returns without a lead time, are simply skipped.

Run:
    cd backend
    python -m app.ml.lead_time_collector            # collects one snapshot
    python -m app.ml.lead_time_collector --limit 50 # cap parts (API quota)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Persistent observed panel — one CSV, appended weekly. Lives under seeds/data
# alongside the other real datasets (this is the accumulating data moat).
PANEL_DIR = Path(__file__).resolve().parents[2] / "seeds" / "data" / "lead_time_panel"
PANEL_PATH = PANEL_DIR / "observed_lead_times.csv"

PANEL_COLUMNS = [
    "snapshot_date",   # YYYY-MM-DD the quote was observed
    "mpn",             # manufacturer part number (join key to components)
    "manufacturer",
    "category",        # from our DB (feature)
    "source",          # "digikey" | "mouser"
    "lead_time_weeks",  # REAL observed target
    "lifecycle_status",  # e.g. "Active", "Obsolete" (feature)
    "stock",           # units in stock at observation (feature)
    "unit_price",      # USD at lowest break (feature / context)
]


async def _collect_async(limit: Optional[int]) -> pd.DataFrame:
    """
    Poll every configured distributor for each part MPN in the DB and return a
    DataFrame of freshly observed rows (may be empty). Never fabricates data.
    """
    from app.core.config import settings

    have_digikey = bool(settings.DIGIKEY_CLIENT_ID and settings.DIGIKEY_CLIENT_SECRET)
    have_mouser = bool(getattr(settings, "MOUSER_API_KEY", ""))

    if not have_digikey and not have_mouser:
        logger.warning(
            "lead-time collector: no DigiKey or Mouser credentials configured — "
            "nothing to collect. This is expected until the API keys are added. "
            "No rows written, no synthetic data generated."
        )
        return pd.DataFrame(columns=PANEL_COLUMNS)

    # Pull the part list from the DB (mpn + category are all we need here).
    from app.core.database import engine
    from app.models.component import Component
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        components = db.query(Component).all()
    if limit:
        components = components[:limit]
    logger.info(
        "lead-time collector: polling %d parts (DigiKey=%s, Mouser=%s)",
        len(components), have_digikey, have_mouser,
    )

    digikey = None
    mouser = None
    if have_digikey:
        from app.core.clients.digikey_client import DigiKeyClient
        digikey = DigiKeyClient(
            settings.DIGIKEY_CLIENT_ID,
            settings.DIGIKEY_CLIENT_SECRET,
            sandbox=settings.DIGIKEY_SANDBOX,
        )
    if have_mouser:
        from app.core.clients.mouser_client import MouserClient
        mouser = MouserClient(settings.MOUSER_API_KEY)

    today = _dt.date.today().isoformat()
    rows: List[dict] = []

    for comp in components:
        mpn = comp.mpn
        if not mpn:
            continue
        category = comp.category or "Unknown"
        manufacturer = comp.manufacturer or ""

        if digikey is not None:
            product = await digikey.search_mpn(mpn)
            if product:
                offer = digikey.parse_offer(product)
                _maybe_append(rows, today, mpn, manufacturer, category, "digikey", offer)

        if mouser is not None:
            part = await mouser.search_mpn(mpn)
            if part:
                offer = mouser.parse_offer(part)
                _maybe_append(rows, today, mpn, manufacturer, category, "mouser", offer)

    return pd.DataFrame(rows, columns=PANEL_COLUMNS)


def _maybe_append(rows, today, mpn, manufacturer, category, source, offer) -> None:
    """Append a row only if the distributor actually returned a lead time."""
    lead_weeks = offer.get("lead_time_weeks")
    if lead_weeks is None:
        return  # real-only: no observed lead time -> no row
    rows.append({
        "snapshot_date": today,
        "mpn": mpn,
        "manufacturer": manufacturer,
        "category": category,
        "source": source,
        "lead_time_weeks": lead_weeks,
        "lifecycle_status": offer.get("lifecycle_status"),
        "stock": offer.get("stock", 0),
        "unit_price": offer.get("price"),
    })


def _merge_dedup(new_rows: pd.DataFrame) -> pd.DataFrame:
    """
    Merge new rows into the existing panel, deduping on
    (snapshot_date, mpn, source) — the newest observation wins.
    """
    if PANEL_PATH.exists():
        existing = pd.read_csv(PANEL_PATH)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows
    combined = combined.drop_duplicates(
        subset=["snapshot_date", "mpn", "source"], keep="last"
    ).reset_index(drop=True)
    return combined


def collect_snapshot(limit: Optional[int] = None) -> dict:
    """
    Collect one lead-time snapshot and persist it to the panel CSV.

    Returns a status dict:
        {"status": "no_keys" | "collected" | "no_data",
         "rows_added": int, "panel_total": int, "panel_path": str}
    Safe to call with no API keys — it no-ops honestly.
    """
    new_rows = asyncio.run(_collect_async(limit))

    if new_rows.empty:
        # Distinguish "no keys / nothing to do" from "keys present but 0 results".
        from app.core.config import settings
        no_keys = not (settings.DIGIKEY_CLIENT_ID or getattr(settings, "MOUSER_API_KEY", ""))
        status = "no_keys" if no_keys else "no_data"
        panel_total = _panel_len()
        logger.info("lead-time collector: 0 new rows (status=%s).", status)
        return {
            "status": status,
            "rows_added": 0,
            "panel_total": panel_total,
            "panel_path": str(PANEL_PATH),
        }

    combined = _merge_dedup(new_rows)
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(PANEL_PATH, index=False)
    logger.info(
        "lead-time collector: wrote %d new rows; panel now holds %d observations at %s",
        len(new_rows), len(combined), PANEL_PATH,
    )
    return {
        "status": "collected",
        "rows_added": int(len(new_rows)),
        "panel_total": int(len(combined)),
        "panel_path": str(PANEL_PATH),
    }


def _panel_len() -> int:
    if PANEL_PATH.exists():
        try:
            return int(len(pd.read_csv(PANEL_PATH)))
        except Exception:
            return 0
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Collect a real lead-time snapshot.")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of parts polled (API quota).")
    args = parser.parse_args()
    result = collect_snapshot(limit=args.limit)
    logger.info("collector result: %s", result)


if __name__ == "__main__":
    main()
