---
phase: 03-live-data-feeds
plan: 03
subsystem: feeds
tags: [portwatch, fred, live-feeds, dashboard, api-endpoint, solve-eta, tdd]

# Dependency graph
requires:
  - phase: 03-live-data-feeds
    plan: 01
    provides: LiveDataCache singleton, CachedFeed dataclass, _port_delay_days() in costs.py
  - phase: 03-live-data-feeds
    plan: 02
    provides: fetch_gpr() and fetch_acled() implemented

provides:
  - fetch_portwatch() — ArcGIS-based congestion proxy for LA/LB, NY/NJ, Savannah
  - fetch_fred_freight() — TSIFRGHT latest value from FRED API
  - GET /api/v1/feeds/status — 4-feed freshness array (Live/Stale/Unavailable)
  - port_delay injected into solve.py effective_eta (before Monte Carlo)
  - FeedStatusCard on Dashboard (60s polling, 3-badge status display, aria-live)
  - feedsAPI in frontend/src/services/api.ts

affects: [solve.py ETA, dashboard-ui, feeds-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - PortWatch congestion proxy: baseline_avg / recent_avg (7-day vs 90-day portcalls ratio)
    - FRED TSIFRGHT: single latest observation via sort_order=desc&limit=1
    - Graceful degradation: ValueError on zero-port-data; port delay try/except in solve.py
    - Feed status TTL: Live = age <= 2x TTL (30min); Stale = older but data exists; Unavailable = data is None
    - Frontend polling: setInterval(60_000) inside useEffect with clearInterval cleanup
    - TDD: RED (8 failing tests) -> GREEN (all 30 pass) -> no REFACTOR needed

key-files:
  modified:
    - backend/app/feeds/fetchers.py — replaced NotImplementedError stubs with full implementations
    - backend/app/api/__init__.py — added feeds router import and include_router
    - backend/app/optimization/solve.py — wired _port_delay_days() into effective_eta
    - backend/tests/test_feeds.py — added 8 new tests (30 total, all passing)
    - frontend/src/services/api.ts — added feedsAPI export object
    - frontend/src/pages/Dashboard.tsx — added feedStatus state, polling, FeedStatusCard JSX
  created:
    - backend/app/api/feeds.py — GET /feeds/status endpoint with Live/Stale/Unavailable logic

key-decisions:
  - "PORTWATCH_URL and FRED_TSIFRGHT_URL hardcoded as module-level constants (T-03-11, T-03-12 SSRF mitigations)"
  - "fetch_portwatch() raises ValueError when no port returns enough data — callers rely on _safe_refresh error handling in scheduler"
  - "Port delay wired into solve.py via local import inside try/except block — graceful degradation on any import or runtime error"
  - "FeedStatusCard uses 4 static placeholder rows on initial render before first API response — avoids empty flash"
  - "/feeds/status endpoint requires no auth (public dashboard data, per ASVS V4 assessment T-03-13)"

# Metrics
duration: 28min
completed: 2026-04-17
---

# Phase 03 Plan 03: PortWatch/FRED Fetchers, /feeds/status, and Dashboard FeedStatusCard

**PortWatch congestion proxy + FRED TSIFRGHT fetchers implemented, GET /feeds/status endpoint live, port delay wired into solve.py ETA, FeedStatusCard widget on Dashboard with 60s polling and Live/Stale/Unavailable badges**

## Performance

- **Duration:** 28 min
- **Completed:** 2026-04-17
- **Tasks:** 2 of 3 complete (Task 3 = human-verify checkpoint, pending)
- **Files modified:** 7

## Accomplishments

- `fetch_portwatch()`: queries IMF PortWatch ArcGIS Feature Service for LA/LB, NY/NJ, Savannah ports; computes congestion_ratio = baseline_avg (90-day) / recent_avg (7-day); skips ports with <14 records; raises ValueError if no port returns data
- `fetch_fred_freight()`: calls FRED API for TSIFRGHT series (sort_order=desc, limit=1); raises ValueError on empty key; skips dot-value observations; FRED_TSIFRGHT_URL hardcoded (T-03-12)
- `backend/app/api/feeds.py`: GET /feeds/status returns 4-item array with name, fetched_at, status, value_summary; TTL = 15 min; Live if age <= 30 min, Stale if older but data exists, Unavailable if data is None; no auth required (T-03-13)
- `backend/app/api/__init__.py`: feeds router registered after graph router
- `backend/app/optimization/solve.py`: `_port_delay_days()` called after effective_eta calculation, result added to effective_eta; wrapped in try/except for graceful degradation (Rule 2 — correctness requirement)
- `frontend/src/services/api.ts`: `feedsAPI.getStatus()` added after optimizeAPI
- `frontend/src/pages/Dashboard.tsx`: FeedStatusCard with feedStatus state, 60s polling via setInterval, formatFeedTime helper, aria-live="polite", 3 badge variants (green/amber/slate), motion-safe:animate-pulse on Live dot

## Task Commits

Each task committed atomically:

1. **Task 1: fetch_portwatch, fetch_fred_freight, /feeds/status, port delay in solve.py** — `fe91d81` (feat)
2. **Task 2: feedsAPI and FeedStatusCard on Dashboard** — `6fb3f90` (feat)
3. **Task 3: Human verify checkpoint** — pending user verification

## Files Created/Modified

- `backend/app/feeds/fetchers.py` — PORTWATCH_URL + FRED_TSIFRGHT_URL constants, fetch_portwatch(), fetch_fred_freight()
- `backend/app/api/feeds.py` (NEW) — GET /feeds/status with _feed_status() and _value_summary() helpers
- `backend/app/api/__init__.py` — feeds import + include_router added
- `backend/app/optimization/solve.py` — port congestion delay block after effective_eta
- `backend/tests/test_feeds.py` — 8 new tests: portwatch_url_constant, portwatch_congestion_proxy, portwatch_insufficient_data, fred_freight_latest_value, fred_freight_no_key, feed_status_endpoint_all_unavailable, feed_status_endpoint_live, feed_status_endpoint_stale
- `frontend/src/services/api.ts` — feedsAPI export
- `frontend/src/pages/Dashboard.tsx` — feedStatus state, polling, formatFeedTime, FeedStatusCard JSX

## Decisions Made

- PortWatch raises ValueError when no monitored port returns >= 14 records; _safe_refresh in scheduler.py catches this and leaves portwatch.data as previous value
- solve.py port delay uses a local import inside a try/except — avoids circular imports and degrades gracefully if feeds package is unavailable
- FeedStatusCard shows 4 static placeholder rows on initial mount (before first API response) to avoid layout shift
- /feeds/status is unauthenticated (public dashboard data) — consistent with T-03-13 accept disposition in threat model

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all fetcher stubs from Plans 03-01 have been replaced with full implementations.

## Threat Flags

No new threat surface beyond plan's threat model. All T-03-11 through T-03-17 mitigations applied:
- PORTWATCH_URL and FRED_TSIFRGHT_URL hardcoded (T-03-11, T-03-12)
- /feeds/status returns only summaries, no raw API data or credentials (T-03-13)
- FRED API key not logged (T-03-14)
- Frontend grep confirms no API key strings in frontend/src/ (T-03-15)
- portcalls division by zero guarded (T-03-16)
- PortWatch 3 sequential calls at 30s timeout each, scheduler max_instances=1 (T-03-17)

## Pending: Task 3 (Human Verify Checkpoint)

Task 3 is a `checkpoint:human-verify` gate. The user must:

1. Start backend and verify `/api/v1/feeds/status` returns 4 items
2. Start frontend and confirm FeedStatusCard renders on Dashboard
3. Verify status badges show correct colors and feed names
4. Confirm no API calls to external feed sources from browser devtools

See checkpoint message below for exact verification steps.

## Self-Check: PASSED

- FOUND: backend/app/feeds/fetchers.py (contains PORTWATCH_URL, FRED_TSIFRGHT_URL, fetch_portwatch, fetch_fred_freight)
- FOUND: backend/app/api/feeds.py (contains @router.get("/status"))
- FOUND: backend/app/api/__init__.py (contains feeds import and include_router)
- FOUND: backend/app/optimization/solve.py (contains _port_delay_days, effective_eta += port_delay)
- FOUND: frontend/src/services/api.ts (contains feedsAPI)
- FOUND: frontend/src/pages/Dashboard.tsx (contains Live Feeds, feedsAPI.getStatus(), aria-live, motion-safe:animate-pulse, all 3 badge classes)
- FOUND commit: fe91d81 (Task 1)
- FOUND commit: 6fb3f90 (Task 2)
- API key grep: 0 matches in frontend/src/ (FEED-07 PASS)
- TypeScript: npx tsc --noEmit exits 0
- Tests: 30/30 passing in tests/test_feeds.py

---
*Phase: 03-live-data-feeds*
*Completed: 2026-04-17*
