"""
APScheduler 3.x AsyncIOScheduler for 15-minute feed refresh cycle.

Credential-gated feeds are handled EXPLICITLY: if a feed's key is absent we do
not call it, we do not log a misleading "refreshed", and we never invent a
value. We mark the feed `inactive` with the exact env var that is missing, which
/feeds/status surfaces to the UI. Dormant reads as dormant.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.feeds import LiveDataCache, CachedFeed
from app.feeds.fetchers import (
    acled_inactive_reason,
    fetch_acled,
    fetch_fred_freight,
    fetch_gpr,
    fetch_portwatch,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


def build_scheduler(cache: LiveDataCache) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        refresh_all_feeds, 'interval', minutes=15,
        args=[cache], id='feed_refresh',
        max_instances=1, coalesce=True,
    )
    return scheduler


async def refresh_all_feeds(cache: LiveDataCache) -> None:
    import asyncio

    # ACLED is the only feed that CANNOT run without a credential (GPR and
    # PortWatch are keyless; FRED falls back to the keyless CSV endpoint).
    acled_reason = acled_inactive_reason(settings.ACLED_EMAIL, settings.ACLED_KEY)

    await asyncio.gather(
        _safe_refresh(cache.gpr, lambda: fetch_gpr(), "gpr"),
        _refresh_acled(cache.acled, acled_reason),
        _safe_refresh(cache.portwatch, lambda: fetch_portwatch(), "portwatch"),
        _safe_refresh(
            cache.fred_freight,
            lambda: fetch_fred_freight(settings.FRED_API_KEY),
            "fred_freight",
        ),
    )


async def _refresh_acled(feed: CachedFeed, inactive_reason) -> None:
    """Refresh ACLED, or mark it explicitly inactive when creds are absent."""
    if inactive_reason:
        async with feed.lock:
            feed.data = None          # nothing fabricated to fill the gap
            feed.error = None         # not an error — a configuration state
            feed.inactive_reason = inactive_reason
        logger.warning("Feed acled INACTIVE: %s", inactive_reason)
        return
    await _safe_refresh(
        feed, lambda: fetch_acled(settings.ACLED_EMAIL, settings.ACLED_KEY), "acled"
    )


async def _safe_refresh(feed: CachedFeed, fetcher, name: str) -> None:
    async with feed.lock:
        try:
            feed.data = await fetcher()
            feed.fetched_at = datetime.utcnow()
            feed.error = None
            feed.inactive_reason = None
            logger.info("Feed %s refreshed at %s", name, feed.fetched_at.isoformat())
        except Exception as exc:
            feed.error = str(exc)
            logger.warning("Feed %s refresh failed: %s", name, exc)
