---
phase: 01-codebase-hardening
verified: 2026-04-16T17:16:02Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 1: Codebase Hardening Verification Report

**Phase Goal:** The codebase is safe to share publicly and all pre-pivot orphans are removed or ported
**Verified:** 2026-04-16T17:16:02Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Server raises ValueError at startup if SECRET_KEY matches any known default string — JWT forgery is impossible on a deployed instance | VERIFIED | `config.py` line 67: `@field_validator("SECRET_KEY")` with `blocked` set containing 4 defaults and `len(v) < 32` guard. Live test: `Settings(SECRET_KEY='your-secret-key-change-in-production', _env_file=None)` raises `ValidationError` with "SECRET_KEY is insecure" message. |
| 2 | CORS allow_origins reads from env var and rejects cross-origin requests from unlisted domains | VERIFIED | `main.py` line 54: `origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]`. Wildcard `allow_origins=["*"]` is absent (grep returns 0 matches). `config.py` has `ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"`. |
| 3 | Live-pricing and market-intelligence endpoints return 401 for unauthenticated callers | VERIFIED | `live_prices.py`: 3 routes have `current_user: User = Depends(get_current_user)`. `market_intelligence.py`: 6 routes have same guard. 9 tests in `test_auth_guards.py` all pass. |
| 4 | Importing any file in the backend raises no ModuleNotFoundError — no references to the deleted Material model remain | VERIFIED | `prophet_forecaster.py`, `forecast_tasks.py`, `data_pipeline.py`, `celery_app.py` all deleted from disk. `grep -r "Material" backend/app/ --include="*.py"` finds only a comment string in `supplymaven_client.py`. `python -c "import app.main"` exits 0. |
| 5 | Demo login works without error on repeated calls — no duplicate db.add race condition | VERIFIED | `auth.py` lines 75-95: new-user path has `db.add(user); db.commit(); db.refresh(user)`; existing-user path has single `db.commit(); db.refresh(user)` — no redundant `db.add`. 5 tests in `test_demo_login.py` all pass including `test_demo_login_idempotent_user`. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/core/config.py` | SECRET_KEY validator, ALLOWED_ORIGINS field, DEBUG=False default | VERIFIED | Contains `@field_validator("SECRET_KEY")`, `ALLOWED_ORIGINS: str`, `DEBUG: bool = False`, error message with `secrets.token_hex(32)` |
| `backend/app/main.py` | CORS middleware with parsed origin list | VERIFIED | Contains `settings.ALLOWED_ORIGINS.split(",")`; no wildcard |
| `backend/.env.example` | Documented env var template | VERIFIED | Contains `SECRET_KEY=`, `ALLOWED_ORIGINS=`, `DEBUG=true` |
| `backend/tests/test_security_hardening.py` | Unit tests for HARD-01/02/03 | VERIFIED | Contains `test_secret_key_rejects_known_defaults`; 7 tests pass |
| `backend/tests/test_auth_guards.py` | Integration tests for HARD-04 | VERIFIED | Contains `test_live_prices_requires_auth`; 9 tests pass |
| `backend/app/api/live_prices.py` | Auth guard on 3 routes | VERIFIED | 3 occurrences of `current_user: User = Depends(get_current_user)` |
| `backend/app/api/market_intelligence.py` | Auth guard on 6 routes | VERIFIED | 6 occurrences of `current_user: User = Depends(get_current_user)` |
| `backend/app/api/auth.py` | Fixed demo_login | VERIFIED | New-user path: `db.add(user); db.commit(); db.refresh(user)`. Existing-user path: single commit cycle. |
| `backend/app/api/cart.py` | Single-query cart retrieval with JOIN | VERIFIED | Contains `.join(Component, CartItem.component_id == Component.id)` |
| `backend/app/api/components.py` | Subquery aggregation for offer stats | VERIFIED | Contains `.subquery()` for offer stats aggregation |
| `backend/app/optimization/constants.py` | Shared transport constants | VERIFIED | Contains `LTL_BASE_FEE_USD = 75.0`, `KM_PER_MILE = 1.60934`, `CO2_G_PER_TON_MILE = 161.8` |
| `backend/tests/test_demo_login.py` | Integration tests for demo login | VERIFIED | Contains `test_demo_login`; 5 tests pass |
| `docker-compose.yml` | No hardcoded SECRET_KEY, no celery_worker | VERIFIED | `SECRET_KEY: ${SECRET_KEY}` — no hardcoded value. Zero matches for `celery_worker`. |

**Deleted artifacts (expected absent):**

| File | Status |
|------|--------|
| `backend/app/ml/prophet_forecaster.py` | DELETED (confirmed) |
| `backend/app/ml/forecast_tasks.py` | DELETED (confirmed) |
| `backend/app/scrapers/data_pipeline.py` | DELETED (confirmed) |
| `backend/app/core/celery_app.py` | DELETED (confirmed) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `config.py` | `main.py` | `settings.ALLOWED_ORIGINS` in CORS middleware | WIRED | `main.py` line 54 reads `settings.ALLOWED_ORIGINS.split(",")` |
| `auth.py` | `live_prices.py` | `Depends(get_current_user)` on 3 route signatures | WIRED | `from app.api.auth import get_current_user` at line 28; 3 route parameters confirmed |
| `auth.py` | `market_intelligence.py` | `Depends(get_current_user)` on 6 route signatures | WIRED | `from app.api.auth import get_current_user` at line 20; 6 route parameters confirmed |
| `constants.py` | `costs.py` | Import of shared constants | WIRED | `from app.optimization.constants import` at line 13 of costs.py |
| `constants.py` | `sourcing.py` | Import of shared constants | WIRED | `from app.optimization.constants import` at line 15 of sourcing.py |

### Data-Flow Trace (Level 4)

Not applicable — this phase modifies configuration validation, authentication middleware, and database query patterns rather than rendering dynamic UI components.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SECRET_KEY validator rejects default | `Settings(SECRET_KEY='your-secret-key-change-in-production', _env_file=None)` | Raises ValidationError | PASS |
| SECRET_KEY validator rejects short keys | `Settings(SECRET_KEY='tooshort', _env_file=None)` | Raises ValidationError | PASS |
| Backend imports cleanly | `SECRET_KEY=<random> python -c "import app.main"` | `Import OK` — no ModuleNotFoundError | PASS |
| Error message contains generation command | Exception text | Contains `secrets.token_hex(32)` | PASS |
| All 66 tests pass | `pytest tests/ -q` | `66 passed, 38 warnings in 40.20s` | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| HARD-01 | 01-01 | SECRET_KEY raises ValueError at startup if it matches the default dev value | SATISFIED | `@field_validator("SECRET_KEY")` in `config.py`; rejects 4 known defaults and keys < 32 chars; test suite passes |
| HARD-02 | 01-01 | CORS allow_origins restricted to frontend domain via env var (not wildcard) | SATISFIED | `ALLOWED_ORIGINS` field in `config.py`; `main.py` parses env var; wildcard removed |
| HARD-03 | 01-01 | DEBUG defaults to False; stack traces not exposed in production responses | SATISFIED | `DEBUG: bool = False` in `config.py` |
| HARD-04 | 01-01 | Live pricing and market intelligence endpoints require authentication | SATISFIED | 9 routes guarded with `Depends(get_current_user)`; 9 auth tests pass |
| HARD-05 | 01-02 | Orphaned pre-pivot files removed or ported to Component/DistributorOffer schema | SATISFIED | 4 files deleted; no ModuleNotFoundError on backend import; no remaining `Material` references in Python imports |
| HARD-06 | 01-03 | Demo login duplicate db.add bug fixed | SATISFIED | New-user path: `db.add` before `db.commit`; existing-user path: single commit; 5 idempotency tests pass |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/core/config.py` | 15 | `SECRET_KEY: str = "your-secret-key-change-in-production"` (default value kept) | Info | The default value is retained as the field default, but the `@field_validator` catches it at startup before any server can accept requests. This is intentional — the validator IS the guard. The insecure default is never reachable in a running instance. |

No blockers found.

### Human Verification Required

No human verification required. All five success criteria are fully verifiable programmatically, and all tests pass.

### Gaps Summary

No gaps. All 5 roadmap success criteria are verified against the actual codebase:

1. SECRET_KEY validator fires at Settings() instantiation — server refuses to boot with weak key.
2. CORS reads `settings.ALLOWED_ORIGINS` env var with DEBUG-conditional localhost inclusion.
3. All 9 live-price and market-intelligence routes require Bearer token authentication.
4. Backend imports cleanly with no ModuleNotFoundError; all 4 orphaned files deleted; no Material model references remain.
5. Demo login persists new users correctly and updates existing users with a single commit cycle; 5 integration tests confirm idempotency.

---

_Verified: 2026-04-16T17:16:02Z_
_Verifier: Claude (gsd-verifier)_
