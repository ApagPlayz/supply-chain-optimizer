"""
APScheduler 3.x AsyncIOScheduler for 15-minute feed refresh cycle.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.feeds import LiveDataCache, CachedFeed
from app.feeds.fetchers import fetch_gpr, fetch_acled, fetch_portwatch, fetch_fred_freight
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
    await asyncio.gather(
        _safe_refresh(cache.gpr, lambda: fetch_gpr(), "gpr"),
        _safe_refresh(cache.acled, lambda: fetch_acled(settings.ACLED_EMAIL, settings.ACLED_KEY), "acled"),
        _safe_refresh(cache.portwatch, lambda: fetch_portwatch(), "portwatch"),
        _safe_refresh(cache.fred_freight, lambda: fetch_fred_freight(settings.FRED_API_KEY), "fred_freight"),
    )


async def _safe_refresh(feed: CachedFeed, fetcher, name: str) -> None:
    async with feed.lock:
        try:
            feed.data = await fetcher()
            feed.fetched_at = datetime.utcnow()
            feed.error = None
            logger.info("Feed %s refreshed at %s", name, feed.fetched_at.isoformat())
        except Exception as exc:
            feed.error = str(exc)
            logger.warning("Feed %s refresh failed: %s", name, exc)
