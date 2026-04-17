---
phase: 03-live-data-feeds
plan: 01
subsystem: api
tags: [apscheduler, asyncio, live-feeds, cp-sat, optimization, risk-surcharge]

# Dependency graph
requires:
  - phase: 02-graph-ml
    provides: _graph_surcharge_cents pattern in sourcing.py that _feed_risk_cents mirrors
  - phase: 01-hardening
    provides: singleton pattern (app/ml/__init__.py, app/graph/__init__.py) mirrored exactly

provides:
  - LiveDataCache singleton (get_live_data_cache / set_live_data_cache)
  - CachedFeed dataclass with per-feed asyncio.Lock
  - APScheduler build_scheduler() with 15-min feed_refresh job and graceful shutdown
  - Placeholder fetchers (fetch_gpr, fetch_acled, fetch_portwatch, fetch_fred_freight)
  - _feed_risk_cents() wired into CP-SAT objective alongside graph surcharges
  - _port_delay_days() in costs.py for additive port congestion lead time delay
  - ACLED_EMAIL and ACLED_KEY in Settings (config.py)
  - apscheduler==3.11.2 and openpyxl in requirements_minimal.txt

affects: [03-02-live-data-feeds, 03-03-live-data-feeds, optimization-sourcing, optimization-costs]

# Tech tracking
tech-stack:
  added: [apscheduler==3.11.2, openpyxl]
  patterns:
    - Singleton cache pattern (mirrors app/ml/__init__.py and app/graph/__init__.py exactly)
    - Local import pattern for circular dep avoidance (from app.feeds import get_live_data_cache inside solve_sourcing)
    - Graceful degradation: all feed consumers check cache is None before use, return 0/0.0 fallback
    - APScheduler max_instances=1 + coalesce=True to prevent concurrent refresh floods (T-03-03)
    - 15% surcharge ceiling matching graph surcharge ceiling (T-03-04)

key-files:
  created:
    - backend/app/feeds/__init__.py
    - backend/app/feeds/fetchers.py
    - backend/app/feeds/scheduler.py
    - backend/tests/test_feeds.py
  modified:
    - backend/app/main.py
    - backend/app/core/config.py
    - backend/requirements_minimal.txt
    - backend/app/optimization/sourcing.py
    - backend/app/optimization/costs.py

key-decisions:
  - "GPR + ACLED surcharges implemented as _feed_risk_cents() additive term in CP-SAT alongside _graph_surcharge_cents() — clean signal separation, same 15% ceiling"
  - "PortWatch congestion mapped to nearest of 3 US ports (LA/LB, NY/NJ, Savannah) by haversine — additive delay on top of ML lead time prediction"
  - "All fetcher bodies left as NotImplementedError stubs — Plans 02/03 fill in the implementations without touching the infrastructure"
  - "ACLED keys stored only in Settings (config.py) and consumed only in scheduler.py — never in frontend or logged at INFO level (T-03-02)"

patterns-established:
  - "Feed singleton: _cache module-level var with get/set functions, mirrors ml/__init__.py exactly"
  - "Graceful degradation: if cache is None: return 0 / return 0.0 at entry of every feed consumer"
  - "Lifespan feeds block: try/except wrapping _scheduler startup; shutdown(wait=False) after yield"
  - "Local import pattern: from app.feeds import get_live_data_cache inside solve_sourcing() to avoid circular imports at module load"

requirements-completed: [FEED-05, FEED-06, FEED-07]

# Metrics
duration: 17min
completed: 2026-04-17
---

# Phase 03 Plan 01: Live Data Feeds Infrastructure Summary

**LiveDataCache singleton + APScheduler 15-min refresh wired into lifespan, with _feed_risk_cents() and _port_delay_days() integrated into CP-SAT and ETA, both degrading gracefully to 0 when feeds unavailable**

## Performance

- **Duration:** 17 min
- **Started:** 2026-04-17T14:08:54Z
- **Completed:** 2026-04-17T14:25:49Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- LiveDataCache singleton with 4 CachedFeed fields and per-feed asyncio.Lock; mirrors ml/__init__.py and graph/__init__.py patterns exactly
- APScheduler AsyncIOScheduler with 15-min feed_refresh job (max_instances=1, coalesce=True) wired into lifespan startup/shutdown in main.py
- _feed_risk_cents() added to sourcing.py: GPR (Chinese-origin) + ACLED (distributor country) surcharges with 15% ceiling, integrated as feed_surcharge_terms in CP-SAT model.Minimize()
- _port_delay_days() added to costs.py: haversine-based nearest-port matching for LA/LB, NY/NJ, Savannah with congestion_ratio delay formula
- 13 unit tests all passing, no regressions in sourcing/costs/strategies test suites

## Task Commits

Each task was committed atomically:

1. **Task 1: Create app/feeds/ package, LiveDataCache, scheduler, lifespan wiring, dependencies** - `4de0459` (feat)
2. **Task 2: Add _feed_risk_cents() and _port_delay_days() with graceful degradation** - `3d5d60e` (feat)

_Note: TDD tasks — tests written before implementation (RED verified), then implementation made them pass (GREEN)._

## Files Created/Modified
- `backend/app/feeds/__init__.py` - LiveDataCache singleton with CachedFeed dataclass and per-feed asyncio.Lock
- `backend/app/feeds/fetchers.py` - Stub async fetchers: fetch_gpr, fetch_acled, fetch_portwatch, fetch_fred_freight
- `backend/app/feeds/scheduler.py` - APScheduler build_scheduler() with 15-min feed_refresh job and _safe_refresh helper
- `backend/app/main.py` - Feeds lifespan block added after graph build block with scheduler startup/shutdown
- `backend/app/core/config.py` - Added ACLED_EMAIL and ACLED_KEY to Settings
- `backend/requirements_minimal.txt` - Added apscheduler==3.11.2 and openpyxl
- `backend/app/optimization/sourcing.py` - Added distributor_country to Offer, _feed_risk_cents(), feed_surcharge_terms in model.Minimize()
- `backend/app/optimization/costs.py` - Added _PORT_COORDS, _PORT_MAX_DELAY, _port_delay_days()
- `backend/tests/test_feeds.py` - 13 unit tests covering cache init, singleton, lock, scheduler, graceful degradation, surcharge ceiling, port delay

## Decisions Made
- Implemented _feed_risk_cents() as a direct additive term in the CP-SAT objective alongside _graph_surcharge_cents(), using the same 15% ceiling — clean signal separation without complicating the existing risk premium structure
- Haversine nearest-port matching uses only 3 US ports (LA/LB, NY/NJ, Savannah) — sufficient coverage for 92 distributors, all major import corridors represented
- Fetcher stubs raise NotImplementedError with plan references — Plans 02/03 fill in the bodies without touching infrastructure

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

The following fetcher functions are intentional stubs (NotImplementedError), to be implemented by Plans 03-02 and 03-03:

| File | Function | Implementing Plan |
|------|----------|-------------------|
| `backend/app/feeds/fetchers.py` | `fetch_gpr()` | Plan 03-02 |
| `backend/app/feeds/fetchers.py` | `fetch_acled()` | Plan 03-02 |
| `backend/app/feeds/fetchers.py` | `fetch_portwatch()` | Plan 03-03 |
| `backend/app/feeds/fetchers.py` | `fetch_fred_freight()` | Plan 03-03 |

These stubs do not prevent this plan's goal: the infrastructure (singleton, scheduler, optimizer integration) is fully functional. The _safe_refresh wrapper catches NotImplementedError and logs a warning, so the server starts cleanly with feeds in "unavailable" state until Plans 02/03 implement the bodies.

## Threat Flags

No new threat surface beyond plan's threat model. ACLED keys confirmed not leaking beyond config.py and scheduler.py (verified via grep).

## Issues Encountered
None - all tests passed first-run after implementation.

## User Setup Required
None — ACLED_EMAIL and ACLED_KEY added to Settings with empty-string defaults. No immediate action required until Plan 03-02 implements the actual ACLED fetcher.

## Next Phase Readiness
- Plans 03-02 and 03-03 can now implement fetcher bodies in fetchers.py independently
- Optimizer integration points (_feed_risk_cents, _port_delay_days) are live and will activate automatically when feeds become available
- APScheduler will call refresh_all_feeds() every 15 minutes once fetchers are implemented; graceful degradation ensures no 500 errors in the meantime

## Self-Check: PASSED

- FOUND: backend/app/feeds/__init__.py
- FOUND: backend/app/feeds/fetchers.py
- FOUND: backend/app/feeds/scheduler.py
- FOUND: backend/tests/test_feeds.py
- FOUND: .planning/phases/03-live-data-feeds/03-01-SUMMARY.md
- FOUND commit: 4de0459 (Task 1)
- FOUND commit: 3d5d60e (Task 2)

---
*Phase: 03-live-data-feeds*
*Completed: 2026-04-17*
