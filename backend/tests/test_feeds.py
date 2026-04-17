"""
Unit tests for app/feeds/ package — LiveDataCache, scheduler, and optimizer integration.
"""
from __future__ import annotations
import asyncio
import math
import pytest

import app.feeds as feeds_module
from app.feeds import CachedFeed, LiveDataCache, get_live_data_cache, set_live_data_cache


# ── Task 1: Cache and scheduler tests ─────────────────────────────────────────

def test_cache_init():
    """LiveDataCache initializes with all 4 CachedFeed fields having data=None."""
    cache = LiveDataCache()
    assert cache.gpr.data is None
    assert cache.acled.data is None
    assert cache.portwatch.data is None
    assert cache.fred_freight.data is None


def test_singleton_set_get():
    """set_live_data_cache() then get_live_data_cache() returns same instance."""
    cache = LiveDataCache()
    set_live_data_cache(cache)
    assert get_live_data_cache() is cache
    # Reset for test isolation
    feeds_module._cache = None


def test_singleton_default_none():
    """get_live_data_cache() returns None before set_live_data_cache() is called."""
    # Ensure clean state
    feeds_module._cache = None
    assert get_live_data_cache() is None


def test_cached_feed_has_lock():
    """CachedFeed.lock is an asyncio.Lock instance."""
    feed = CachedFeed()
    assert isinstance(feed.lock, asyncio.Lock)


def test_build_scheduler_returns_scheduler():
    """build_scheduler returns an AsyncIOScheduler with a job named 'feed_refresh'."""
    from app.feeds.scheduler import build_scheduler
    cache = LiveDataCache()
    scheduler = build_scheduler(cache)
    assert hasattr(scheduler, 'get_job')
    assert scheduler.get_job('feed_refresh') is not None


# ── Task 2: _feed_risk_cents and _port_delay_days tests ───────────────────────

def _make_offer(price_usd: float = 10.0) -> object:
    """Create a minimal Offer-like object for testing."""
    from app.optimization.sourcing import Offer
    return Offer(
        component_id=1,
        distributor_id=1,
        distributor_name="TestDist",
        price_usd=price_usd,
        stock=100,
        moq=1,
        is_domestic=True,
        dist_km_from_depot=500.0,
        risk_score=0.3,
        is_chinese_origin=False,
    )


def test_feed_risk_cents_cache_none():
    """_feed_risk_cents returns 0 when cache is None."""
    from app.optimization.sourcing import _feed_risk_cents
    offer = _make_offer(price_usd=10.0)
    assert _feed_risk_cents(offer, "US", False, None) == 0


def test_feed_risk_cents_empty_feeds():
    """_feed_risk_cents returns 0 when all feed data is None."""
    from app.optimization.sourcing import _feed_risk_cents
    offer = _make_offer(price_usd=10.0)
    cache = LiveDataCache()
    assert _feed_risk_cents(offer, "US", False, cache) == 0


def test_feed_risk_cents_gpr_elevated():
    """_feed_risk_cents returns positive surcharge when GPR is elevated (>100) and is_chinese_origin=True."""
    from app.optimization.sourcing import _feed_risk_cents
    offer = _make_offer(price_usd=10.0)
    cache = LiveDataCache()
    cache.gpr.data = 200.0  # above baseline of 100
    result = _feed_risk_cents(offer, "US", True, cache)
    assert result > 0


def test_feed_risk_cents_ceiling():
    """_feed_risk_cents result is at most floor(0.15 * unit_price_cents)."""
    from app.optimization.sourcing import _feed_risk_cents
    offer = _make_offer(price_usd=10.0)
    cache = LiveDataCache()
    cache.gpr.data = 500.0  # maximum GPR
    cache.acled.data = {"CN": 1000}
    result = _feed_risk_cents(offer, "CN", True, cache)
    ceiling = int(math.floor(0.15 * int(round(offer.price_usd * 100))))
    assert result <= ceiling


def test_feed_risk_cents_acled_signal():
    """_feed_risk_cents returns positive surcharge from ACLED conflict data."""
    from app.optimization.sourcing import _feed_risk_cents
    offer = _make_offer(price_usd=10.0)
    cache = LiveDataCache()
    cache.acled.data = {"US": 50}
    result = _feed_risk_cents(offer, "US", False, cache)
    assert result > 0


def test_port_delay_cache_none():
    """_port_delay_days returns 0.0 when cache is None."""
    from app.optimization.costs import _port_delay_days
    assert _port_delay_days(33.7, -118.2, None) == 0.0


def test_port_delay_la_congested():
    """_port_delay_days returns ~1.5 days for LA/LB with congestion_ratio=1.5."""
    from app.optimization.costs import _port_delay_days
    cache = LiveDataCache()
    cache.portwatch.data = {"LA_LB": 1.5, "NY_NJ": 1.0, "SAVANNAH": 1.0}
    result = _port_delay_days(33.7, -118.2, cache)
    # (1.5 - 1.0) * 3.0 = 1.5
    assert result == pytest.approx(1.5, abs=0.1)


def test_port_delay_no_congestion():
    """_port_delay_days returns 0.0 when all port congestion ratios are 1.0."""
    from app.optimization.costs import _port_delay_days
    cache = LiveDataCache()
    cache.portwatch.data = {"LA_LB": 1.0, "NY_NJ": 1.0, "SAVANNAH": 1.0}
    result = _port_delay_days(33.7, -118.2, cache)
    assert result == 0.0
