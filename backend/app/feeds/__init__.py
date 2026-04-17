"""
Live Data Feeds Cache.

Four external signals cached in-memory with TTL:
  1. GPR Index (Caldara-Iacoviello) — geopolitical risk
  2. ACLED conflict events — 90-day rolling by country
  3. IMF PortWatch — port congestion proxy
  4. FRED TSIFRGHT — freight transportation index

Call get_live_data_cache() to get the current cache, or None if feeds
have not been initialized yet (initializes at startup via lifespan).
"""
from __future__ import annotations
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
import asyncio


@dataclass
class CachedFeed:
    data: object = None
    fetched_at: Optional[datetime] = None
    error: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class LiveDataCache:
    gpr: CachedFeed = field(default_factory=CachedFeed)
    acled: CachedFeed = field(default_factory=CachedFeed)
    portwatch: CachedFeed = field(default_factory=CachedFeed)
    fred_freight: CachedFeed = field(default_factory=CachedFeed)


_cache: Optional[LiveDataCache] = None


def get_live_data_cache() -> Optional[LiveDataCache]:
    return _cache


def set_live_data_cache(cache: LiveDataCache) -> None:
    global _cache
    _cache = cache
