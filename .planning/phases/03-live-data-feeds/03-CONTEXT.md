---
phase: 03-live-data-feeds
created: 2026-04-16
mode: discuss
---

# Phase 3 Context: Live Data Feeds

**Phase Goal:** Four external signals (GPR, ACLED, IMF PortWatch, FRED freight) refresh on schedule, degrade gracefully on outage, and visibly affect risk scores and lead time modifiers in the optimizer.

---

## Prior Decisions (Locked from Phase 1/2 / ROADMAP Architectural Constraints)

- All external API calls through FastAPI backend only — no API keys in frontend bundle or git log
- `CachedFeed` dataclass with `asyncio.Lock` and TTL per feed type
- `APScheduler AsyncIOScheduler` shut down in lifespan cleanup (after `yield`)
- 15-minute APScheduler refresh interval for all four feeds
- Graceful degradation: all live feed consumers check `CachedFeed.data is None` before use; optimizer returns valid result with static fallback scores when any feed is unavailable
- Demo resilience: no 500 errors on API outage, UI labels each feed as [stale] or [unavailable]

---

## Decisions

### 1. Feed → CP-SAT Injection Architecture
**Country-aware per-offer surcharges — separate additive term alongside graph surcharges.**

GPR (geopolitical risk) wires into Chinese-origin component risk. ACLED (conflict event count) wires into distributor-country risk. Both are implemented as a new `_feed_risk_cents()` helper in `sourcing.py`, called in the CP-SAT objective alongside the existing `_graph_surcharge_cents()`.

```python
# In sourcing.py CP-SAT objective:
graph_surcharge = _graph_surcharge_cents(did, offer_key, _gs)
feed_surcharge  = _feed_risk_cents(distributor.country, is_chinese_origin, _ldc)
# _ldc = get_live_data_cache()
objective += graph_surcharge + feed_surcharge
```

`_feed_risk_cents()` inputs:
- `distributor.country` → look up ACLED 90-day conflict count for that country → normalize to [0, 1] → surcharge = `floor(normalized × ceiling × unit_price_cents)`
- `is_chinese_origin` (component.manufacturer_country == "CN") → scale by current GPR index → surcharge = `floor(gpr_normalized × ceiling × unit_price_cents)`
- Apply same 15% unit price ceiling as graph surcharges (from ROADMAP architectural constraints)
- When `_ldc` is None or feed data is None, `_feed_risk_cents()` returns 0 (graceful degradation)

**Why country-aware over augmenting macro_stress:** Separate signal — all components/distributors from the same country get the same treatment regardless of ML stress probability. More precise, more impressive in interview demos. Signal separation is clean.

### 2. PortWatch Lead Time Integration
**Additive days on top of ML lead time prediction, geo-matched per distributor.**

Each distributor is mapped to its nearest monitored US port (LA/LB, NY/NJ, Savannah) by haversine distance. When the port's current wait-time exceeds a baseline threshold, the excess is added to the ML-predicted ETA.

```python
# In costs.py:
base_eta = ml_lead_time_days(offer, dist_km, ...)
port_delay = _port_delay_days(distributor.lat, distributor.lon, _ldc)
eta = base_eta + port_delay
```

`_port_delay_days()` implementation:
- Map distributor → nearest of 3 ports by haversine
- Baseline thresholds (approximate): LA/LB = 1.5d, NY/NJ = 1.0d, Savannah = 0.5d
- `port_delay = max(0, current_wait_days - baseline)` — only add delay above baseline
- Returns 0 when `_ldc` is None or PortWatch feed unavailable

### 3. Feeds Module Structure
**New `app/feeds/` package mirroring `app/ml/` and `app/graph/` pattern exactly.**

```
backend/app/feeds/
  __init__.py      ← LiveDataCache dataclass, _cache singleton, get_live_data_cache() / set_live_data_cache()
  fetchers.py      ← fetch_gpr(), fetch_acled(), fetch_portwatch(), fetch_fred_freight()
  scheduler.py     ← build_scheduler() returning AsyncIOScheduler; called in lifespan
```

`LiveDataCache` fields:
- `gpr_index: Optional[float]` — latest GPR monthly value (0–500+ range)
- `acled_by_country: Optional[dict[str, int]]` — {country_code: 90d conflict count}
- `portwatch_by_port: Optional[dict[str, float]]` — {port_code: wait_days} e.g. {"LA_LB": 2.1}
- `fred_tsifrght: Optional[float]` — latest TSIFRGHT freight index value
- `fetched_at: dict[str, Optional[datetime]]` — last fetch timestamp per feed key
- `asyncio.Lock` per feed for concurrent refresh safety

Lifespan wiring in `main.py`:
```python
# After graph build block:
try:
    from app.feeds.scheduler import build_scheduler
    from app.feeds import set_live_data_cache, LiveDataCache
    _ldc = LiveDataCache()
    set_live_data_cache(_ldc)
    _scheduler = build_scheduler(_ldc)
    _scheduler.start()
    # initial fetch (fire-and-forget)
except Exception as exc:
    logging.getLogger(__name__).warning("Feed scheduler start skipped: %s", exc)

yield

# Cleanup:
try:
    _scheduler.shutdown(wait=False)
except Exception:
    pass
```

### 4. Dashboard Freshness UI
**Compact "Live Feeds" status section added to the existing Dashboard page.**

4 rows (GPR, ACLED, PortWatch, FRED), each showing: feed name, last-fetched timestamp, status badge.

```
[ Live Feeds ]  ────────────────────────
 GPR Index     2026-04-16 14:32  ● Live
 ACLED         2026-04-16 14:32  ● Live
 IMF PortWatch 2026-04-16 14:17  ⚠ Stale
 FRED Freight  2026-04-16 14:32  ● Live
```

Status logic:
- **Live** — fetched_at within 2× TTL (e.g., within 30 min for 15-min schedule)
- **Stale** — fetched_at older than 2× TTL but data is non-null
- **Unavailable** — data is null (API key missing or all retries failed)

Backend: `GET /api/v1/feeds/status` endpoint returns `[{name, fetched_at, status, value_summary}]`.
Frontend: New `FeedStatusCard` component added to `DashboardPage.tsx`, below existing stats cards.

---

## Codebase Integration Points

| File | Change |
|------|--------|
| `backend/app/feeds/__init__.py` | NEW — LiveDataCache singleton, get/set |
| `backend/app/feeds/fetchers.py` | NEW — 4 async fetch functions |
| `backend/app/feeds/scheduler.py` | NEW — APScheduler setup |
| `backend/app/main.py` | Add feeds lifespan block (after graph build block) |
| `backend/app/api/__init__.py` | Register feeds router |
| `backend/app/api/feeds.py` | NEW — GET /feeds/status endpoint |
| `backend/app/optimization/sourcing.py` | Add `_feed_risk_cents()` + call in CP-SAT objective |
| `backend/app/optimization/costs.py` | Add `_port_delay_days()` + apply to ETA |
| `frontend/src/pages/DashboardPage.tsx` | Add FeedStatusCard section |
| `frontend/src/services/api.ts` | Add fetchFeedStatus() API call |

---

## Out of Scope for Phase 3

- Frontend chart of historical feed values over time (v2 / Phase 4 enhancement)
- ACLED per-city granularity (country-level sufficient for distributor risk)
- Alpha Vantage commodity prices (different domain — materials pricing, not supply chain risk)
- POST /admin/refresh-feeds endpoint (v2 backlog per REQUIREMENTS.md MLOPS scope)

---

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `.planning/ROADMAP.md` — Phase 3 plan breakdown (03-01, 03-02, 03-03) and architectural constraints
- `.planning/REQUIREMENTS.md` — FEED-01 through FEED-07 requirement definitions
- `backend/app/ml/__init__.py` — Singleton pattern to mirror exactly for `app/feeds/__init__.py`
- `backend/app/graph/__init__.py` — Second singleton pattern example
- `backend/app/main.py` — Lifespan wiring pattern for ML + graph blocks (feeds block goes after)
- `backend/app/optimization/sourcing.py` — CP-SAT injection point; find `_graph_surcharge_cents()` call; `_feed_risk_cents()` goes in same objective block
- `backend/app/optimization/costs.py` — `ml_lead_time_days()` call; `_port_delay_days()` result added after
- `backend/app/core/data_fetcher.py` — Existing async httpx pattern for FRED; reuse or consolidate into fetchers.py

---

*Phase: 03-live-data-feeds*
*Context gathered: 2026-04-16*
