---
phase: 03-live-data-feeds
plan: 02
subsystem: api
tags: [httpx, openpyxl, asyncio, acled, gpr, geopolitical-risk, live-feeds, testing]

# Dependency graph
requires:
  - phase: 03-live-data-feeds
    plan: 01
    provides: LiveDataCache singleton, CachedFeed stubs fetch_gpr/fetch_acled, openpyxl in requirements

provides:
  - fetch_gpr() downloads GPR XLSX from hardcoded URL, offloads openpyxl parse to asyncio.to_thread, returns latest float
  - fetch_acled() authenticates via query params (key + email), returns {ISO3: count} dict for 90-day conflict events
  - Graceful degradation: returns None when ACLED_EMAIL/ACLED_KEY missing or empty
  - ACLED_EMAIL and ACLED_KEY changed to Optional[str]=None in Settings so both empty-string and unset trigger None path
  - 9 new unit tests (3 GPR + 6 ACLED) with fully mocked HTTP — no real API calls in test suite

affects: [03-03-live-data-feeds, optimization-sourcing, feeds-scheduler]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.to_thread wrapping synchronous openpyxl calls to avoid blocking FastAPI event loop
    - unittest.mock.AsyncMock + patch for mocking httpx.AsyncClient context manager in async tests
    - Query param auth pattern for ACLED (key + email in params dict, no OAuth, no Bearer header)
    - Optional[str]=None credential fields trigger graceful degradation via `if not email or not key`

key-files:
  created: []
  modified:
    - backend/app/feeds/fetchers.py
    - backend/app/core/config.py
    - backend/tests/test_feeds.py

key-decisions:
  - "ACLED auth implemented as pure query params (key + email) — NOT OAuth; the prior research incorrectly described OAuth2 client credentials flow; ACLED's actual API uses simple query param authentication"
  - "ACLED_EMAIL/ACLED_KEY changed from str='' to Optional[str]=None so that both unset and empty-string cases trigger the graceful degradation return-None path via `if not email or not key`"
  - "GPR parse offloaded to asyncio.to_thread with read_only=True openpyxl mode — prevents event loop blocking on large XLSX downloads (T-03-10)"

patterns-established:
  - "asyncio.to_thread(_parse, content): wrap any synchronous library call inside an async fetcher"
  - "Hardcoded URL constants (GPR_URL, ACLED_API_URL) at module level — never accept user-provided URLs in fetchers"
  - "Credentials checked at function entry with `if not x or not y: return None` before any network call"

requirements-completed: [FEED-01, FEED-02]

# Metrics
duration: 2min
completed: 2026-04-17
---

# Phase 03 Plan 02: Live Data Feeds — GPR and ACLED Fetchers Summary

**fetch_gpr() parses Caldara-Iacoviello XLSX via asyncio.to_thread + openpyxl; fetch_acled() uses query param auth returning {ISO3: count} with graceful None on missing credentials**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-17T14:28:22Z
- **Completed:** 2026-04-17T14:30:23Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- fetch_gpr(): hardcoded GPR_URL constant, httpx download, openpyxl parse offloaded to asyncio.to_thread, reads column B of "GPR" sheet, raises ValueError on empty data — all STRIDE mitigations T-03-05/08/10 satisfied
- fetch_acled(): hardcoded ACLED_API_URL, query param auth (key + email — NO OAuth), 90-day date range, ISO3 aggregation, returns None when credentials missing — T-03-06/07/09 satisfied
- config.py ACLED fields changed to Optional[str]=None so unset and empty-string both degrade gracefully
- 9 new mocked tests (3 GPR + 6 ACLED) pass; full test_feeds.py suite: 22/22 green

## Task Commits

Both TDD tasks committed together as one atomic implementation commit:

1. **Tasks 1+2: fetch_gpr() + fetch_acled() + config update + 9 tests** - `2668e13` (feat)

_Note: TDD — tests written first (RED confirmed via ImportError), then implementation made all 22 tests pass (GREEN)._

## Files Created/Modified
- `backend/app/feeds/fetchers.py` - Replaced fetch_gpr() and fetch_acled() stubs with full implementations; GPR_URL and ACLED_API_URL constants; fetch_portwatch/fetch_fred_freight stubs retained for Plan 03-03
- `backend/app/core/config.py` - ACLED_EMAIL/ACLED_KEY changed from `str = ""` to `Optional[str] = None`; added `from typing import Optional`
- `backend/tests/test_feeds.py` - Added `_make_gpr_xlsx()` helper; 3 GPR tests; 6 ACLED tests using AsyncMock + patch

## Decisions Made
- ACLED auth is pure query params — the prior research described OAuth2 client credentials, but ACLED's actual API uses `key` and `email` as plain GET params. Implemented correctly as query params per the plan's corrected spec.
- Optional[str]=None for ACLED credentials gives cleaner None-path semantics than empty string; `if not email or not key` covers both None and "" uniformly.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

The following fetcher functions remain intentional stubs (NotImplementedError) for Plan 03-03:

| File | Function | Implementing Plan |
|------|----------|-------------------|
| `backend/app/feeds/fetchers.py` | `fetch_portwatch()` | Plan 03-03 |
| `backend/app/feeds/fetchers.py` | `fetch_fred_freight()` | Plan 03-03 |

These stubs do not prevent this plan's goal. The scheduler's `_safe_refresh` wrapper catches NotImplementedError and logs a warning, so the server continues to operate with those feeds in "unavailable" state.

## Threat Flags

No new threat surface. All STRIDE mitigations from plan's threat model applied:

| Threat ID | Mitigation Applied |
|-----------|--------------------|
| T-03-05 | GPR_URL hardcoded constant — verified in fetchers.py line 20 |
| T-03-06 | ACLED_API_URL hardcoded constant — verified in fetchers.py line 57 |
| T-03-07 | email/key never logged — grep confirms 0 matches for `logger.*email\|logger.*key` |
| T-03-08 | openpyxl skips non-numeric column B values; ValueError on empty data |
| T-03-09 | Only iso3 string extracted and counted as integer — no raw ACLED text flows to frontend |
| T-03-10 | asyncio.to_thread + read_only=True + httpx timeout=30s |

## Issues Encountered
None — all 22 tests passed after first implementation.

## User Setup Required
None for this plan. ACLED credentials (ACLED_EMAIL, ACLED_KEY) are optional — fetch_acled() returns None when missing, and the optimizer's _feed_risk_cents() degrades to 0 surcharge. To activate live ACLED data, register at acleddata.com and set both env vars.

## Next Phase Readiness
- Plan 03-03 can implement fetch_portwatch() and fetch_fred_freight() bodies independently
- fetch_gpr() and fetch_acled() are live — APScheduler will call them every 15 minutes once the server starts with valid ACLED credentials
- _feed_risk_cents() in sourcing.py already consumes cache.gpr.data and cache.acled.data — surcharges activate automatically as feeds populate

## Self-Check: PASSED

- FOUND: backend/app/feeds/fetchers.py (contains GPR_URL, ACLED_API_URL, fetch_gpr, fetch_acled implementations)
- FOUND: backend/app/core/config.py (contains Optional[str] = None for both ACLED fields)
- FOUND: backend/tests/test_feeds.py (contains all 9 new tests)
- FOUND commit: 2668e13 (feat(03-02))
- 22/22 tests passing

---
*Phase: 03-live-data-feeds*
*Completed: 2026-04-17*
