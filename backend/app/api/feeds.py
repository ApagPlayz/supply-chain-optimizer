"""
Feed status endpoint — public (no auth required per ASVS V4 assessment).

Returns freshness status for all 4 live data feeds.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter

from app.feeds import get_live_data_cache

router = APIRouter(prefix="/feeds", tags=["feeds"])

# TTL for freshness calculation (feeds refresh every 15 min)
FEED_TTL_MINUTES = 15


def _feed_status(fetched_at: Optional[datetime], data: object) -> str:
    if data is None:
        return "unavailable"
    if fetched_at is None:
        return "unavailable"
    age = datetime.utcnow() - fetched_at
    if age <= timedelta(minutes=FEED_TTL_MINUTES * 2):
        return "live"
    return "stale"


def _value_summary(name: str, data: object) -> Optional[str]:
    if data is None:
        return None
    if name == "gpr":
        return f"GPR: {data:.1f}"
    if name == "acled":
        total = sum(data.values()) if isinstance(data, dict) else 0
        return f"{total} events across {len(data) if isinstance(data, dict) else 0} countries"
    if name == "portwatch":
        if isinstance(data, dict):
            parts = [f"{k}: {v:.2f}" for k, v in data.items()]
            return "; ".join(parts)
        return None
    if name == "fred_freight":
        return f"TSIFRGHT: {data:.1f}"
    return None


@router.get("/status")
async def feed_status():
    """Return freshness status for all 4 live feeds.

    No auth required — this is public dashboard data (per ASVS V4 assessment).
    T-03-13: Returns only names, timestamps, and value summaries — no credentials,
    no raw API responses.
    """
    cache = get_live_data_cache()
    if cache is None:
        return [
            {"name": n, "fetched_at": None, "status": "unavailable", "value_summary": None}
            for n in ["GPR Index", "ACLED Conflict", "IMF PortWatch", "FRED Freight"]
        ]

    feed_map = [
        ("GPR Index", "gpr", cache.gpr),
        ("ACLED Conflict", "acled", cache.acled),
        ("IMF PortWatch", "portwatch", cache.portwatch),
        ("FRED Freight", "fred_freight", cache.fred_freight),
    ]
    results = []
    for display_name, key, feed in feed_map:
        results.append({
            "name": display_name,
            "fetched_at": feed.fetched_at.isoformat() + "Z" if feed.fetched_at else None,
            "status": _feed_status(feed.fetched_at, feed.data),
            "value_summary": _value_summary(key, feed.data),
        })
    return results
