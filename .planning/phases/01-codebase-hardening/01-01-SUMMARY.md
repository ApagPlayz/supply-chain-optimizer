---
phase: 01-codebase-hardening
plan: 01
subsystem: security
tags: [fastapi, pydantic-v2, jwt, cors, docker-compose, pytest]

# Dependency graph
requires:
  - phase: 00-initial
    provides: Existing FastAPI app, JWT auth in app/api/auth.py, pydantic-settings config
provides:
  - SECRET_KEY startup validator rejecting 4 known defaults + keys under 32 chars
  - ALLOWED_ORIGINS config field with DEBUG-conditional localhost inclusion
  - DEBUG defaults to False (production-safe)
  - Auth guards (Depends(get_current_user)) on 9 live-price and market-intelligence routes
  - backend/.env.example with documented env vars
  - docker-compose SECRET_KEY read from environment instead of hardcoded
  - pytest TestClient infrastructure (conftest.py with db_session, client, auth_token fixtures)
  - 16 passing tests (7 security hardening + 9 auth guard)
affects: [02-graph-ml, 03-live-feeds, 04-benchmark, 05-forecasting]

# Tech tracking
tech-stack:
  added:
    - pydantic.field_validator (v2 startup validation)
    - fastapi.testclient.TestClient (integration test harness)
  patterns:
    - Startup-time config validation via @field_validator
    - Comma-separated env-var lists parsed at app bootstrap
    - Dependency-injected auth guards reusing app.api.auth.get_current_user

key-files:
  created:
    - backend/.env.example
    - backend/tests/test_security_hardening.py
    - backend/tests/test_auth_guards.py
  modified:
    - backend/app/core/config.py
    - backend/app/main.py
    - backend/app/api/live_prices.py
    - backend/app/api/market_intelligence.py
    - backend/tests/conftest.py
    - docker-compose.yml
    - backend/.env (not committed — gitignored; contains real secret)

key-decisions:
  - "SECRET_KEY validator raises ValueError at Settings() instantiation rather than deferred check — server refuses to start with a weak key"
  - "DEBUG flag controls auto-inclusion of localhost origins — eliminates need for two env files in dev"
  - "sync_component_prices passes current_user explicitly when invoking get_live_prices internally — direct function call bypasses FastAPI DI"
  - "docker-compose uses ${SECRET_KEY} with no default — fails fast in prod if operator forgot to set it"

patterns-established:
  - "Pydantic v2 field_validator for security-critical config: rejects bad values at boot, error message includes remediation command"
  - "CORS middleware reads from settings.ALLOWED_ORIGINS and conditionally adds dev origins when DEBUG is true"
  - "All sensitive routes use Depends(get_current_user) — centralized, consistent with cart.py and components.py"

requirements-completed: [HARD-01, HARD-02, HARD-03, HARD-04]

# Metrics
duration: 4min
completed: 2026-04-16
---

# Phase 01 Plan 01: Codebase Hardening — Critical Security Fixes Summary

**Pydantic v2 SECRET_KEY validator rejecting defaults, explicit CORS origin list with DEBUG-conditional localhost, DEBUG=False by default, and Depends(get_current_user) auth guards on 9 live-price/market routes**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-16T16:49:22Z
- **Completed:** 2026-04-16T16:52:49Z
- **Tasks:** 2 (both auto-executed)
- **Files modified:** 7 (+ 3 new)

## Accomplishments

- SECRET_KEY startup validator blocks 4 known defaults and any key under 32 chars; error message gives copy-paste generation command
- CORS middleware now reads a parsed list from ALLOWED_ORIGINS; wildcard+credentials anti-pattern eliminated
- DEBUG defaults to False — production no longer ships with SQL echo and stack traces enabled
- Auth guards added to 3 live-price endpoints and 6 market-intelligence endpoints — all return 401 unauthenticated
- docker-compose.yml no longer hardcodes SECRET_KEY; reads ${SECRET_KEY} from environment
- backend/.env.example onboards new developers with documented env vars and generation command
- pytest TestClient harness + 16 green tests (7 security hardening + 9 auth guards)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 test stubs + config hardening + CORS + .env.example + docker-compose** — `a870943` (feat)
2. **Task 2: Auth guards on live-prices and market-intelligence endpoints** — `1434c58` (feat)

## Files Created/Modified

- `backend/app/core/config.py` — Added `@field_validator("SECRET_KEY")`, `ALLOWED_ORIGINS: str`, flipped `DEBUG: bool = False`
- `backend/app/main.py` — Replaced `allow_origins=["*"]` with parsed origin list + DEBUG-conditional localhost
- `backend/app/api/live_prices.py` — Added `current_user: User = Depends(get_current_user)` to 3 routes + pass-through inside `sync_component_prices`
- `backend/app/api/market_intelligence.py` — Added `current_user: User = Depends(get_current_user)` to 6 routes; added `Depends`, `User`, `get_current_user` imports
- `backend/tests/conftest.py` — Added `db_session`, `client`, `auth_token` fixtures with SECRET_KEY env var set before app import
- `backend/tests/test_security_hardening.py` — 7 tests for HARD-01/02/03
- `backend/tests/test_auth_guards.py` — 9 tests for HARD-04
- `backend/.env.example` — New file documenting all env vars
- `backend/.env` — Regenerated with real 64-char hex SECRET_KEY (gitignored, not committed)
- `docker-compose.yml` — Replaced hardcoded `SECRET_KEY: dev-...` in backend and celery_worker services with `${SECRET_KEY}`; `DEBUG: ${DEBUG:-false}`

## Decisions Made

- **Validator fires at Settings() instantiation** rather than a separate runtime check — the server refuses to boot with a weak key, which is stronger than an 80% mitigation
- **DEBUG-conditional localhost CORS** — eliminates the need for two env files between dev and prod; developers never accidentally lock themselves out in dev
- **Pass-through current_user in `sync_component_prices`** — the existing internal call `await get_live_prices(mpn)` bypasses FastAPI DI, so the authenticated User is forwarded explicitly to satisfy the new required arg
- **`docker-compose` SECRET_KEY has no default** (`${SECRET_KEY}` not `${SECRET_KEY:-default}`) — fail-fast in prod when operator forgets to set it

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `sync_component_prices` internal call would fail after auth guard added**
- **Found during:** Task 2
- **Issue:** After adding `current_user: User = Depends(get_current_user)` to `get_live_prices`, the internal direct call `await get_live_prices(mpn)` at line 276 of `live_prices.py` would raise `TypeError: missing 1 required argument: 'current_user'` — FastAPI only injects dependencies for HTTP requests, not direct Python calls
- **Fix:** Pass the authenticated `current_user` explicitly: `await get_live_prices(mpn, current_user=current_user)`
- **Files modified:** backend/app/api/live_prices.py (line 276)
- **Verification:** Covered by `test_live_prices_sync_requires_auth` (passes)
- **Committed in:** `1434c58` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary correctness fix directly caused by the plan's changes. No scope creep.

## Issues Encountered

- None beyond the deviation above.

## User Setup Required

None — no external services configured. Developers should copy `backend/.env.example` to `backend/.env` and set `SECRET_KEY` using the documented `python -c 'import secrets; print(secrets.token_hex(32))'` command. In production, the SECRET_KEY must be provided via environment variable or secret manager.

## Next Phase Readiness

- All four Critical/Security issues from CONCERNS.md (HARD-01, HARD-02, HARD-03, HARD-04) are closed
- Test harness (TestClient + fixtures) is now available for all subsequent API tests
- Phase 2 (Graph ML) can proceed without blocking on these security issues
- Remaining hardening concerns (orphaned pre-pivot files, broken prophet_forecaster.py) are scoped for plans 01-02 and 01-03 in this same phase

## Self-Check: PASSED

Verified files exist:
- FOUND: backend/app/core/config.py (`@field_validator("SECRET_KEY")` present)
- FOUND: backend/app/main.py (`settings.ALLOWED_ORIGINS.split` present)
- FOUND: backend/app/api/live_prices.py (3x `Depends(get_current_user)`)
- FOUND: backend/app/api/market_intelligence.py (6x `Depends(get_current_user)`)
- FOUND: backend/.env.example
- FOUND: backend/tests/test_security_hardening.py
- FOUND: backend/tests/test_auth_guards.py
- FOUND: backend/tests/conftest.py (TestClient)

Verified commits exist:
- FOUND: a870943 (feat(01-01): harden config)
- FOUND: 1434c58 (feat(01-01): add auth guards)

Verified tests:
- 16 passed (7 security hardening + 9 auth guards)

---
*Phase: 01-codebase-hardening*
*Completed: 2026-04-16*
