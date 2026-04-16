---
phase: 01-codebase-hardening
security_path: .planning/phases/01-codebase-hardening/01-SECURITY.md
asvs_level: 1
block_on: high
audited: 2026-04-16
auditor: gsd-secure-phase
---

# Security Audit — Phase 01: Codebase Hardening

**Phase:** 01 — codebase-hardening
**Threats Closed:** 9/9
**ASVS Level:** 1
**Audit Result:** SECURED

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-1-01 | Spoofing | mitigate | CLOSED | `backend/app/core/config.py:68-84` — `@field_validator("SECRET_KEY")` with `@classmethod`; rejects all 4 known defaults and any key shorter than 32 chars; error message contains `secrets.token_hex(32)` generation command |
| T-1-02 | Information Disclosure | mitigate | CLOSED | `backend/app/main.py:54` — `allow_origins=["*"]` replaced with `[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]`; wildcard CORS eliminated |
| T-1-03 | Information Disclosure | mitigate | CLOSED | `backend/app/core/config.py:21` — `DEBUG: bool = False`; stack traces and SQL echo disabled in production by default |
| T-1-04 | Elevation of Privilege | mitigate | CLOSED | `backend/app/api/live_prices.py:162,192,273` — `current_user: User = Depends(get_current_user)` on all 3 live-prices routes; `backend/app/api/market_intelligence.py:90,142,181,218,263,312` — same guard on all 6 market-intelligence routes; total 9 routes return 401 unauthenticated |
| T-1-05 | Information Disclosure | mitigate | CLOSED | `docker-compose.yml:39` — `SECRET_KEY: ${SECRET_KEY}` with no default; hardcoded value eliminated; `celery_worker` service (which also contained a hardcoded key) removed entirely |
| T-1-06 | Denial of Service | mitigate | CLOSED | `docker-compose.yml` — `celery_worker` service block absent (confirmed plan 01-02); `backend/app/core/celery_app.py` deleted; crash loop on `docker-compose up` no longer possible |
| T-1-07 | Information Disclosure | accept | CLOSED | Accepted risk — see Accepted Risks log below |
| T-1-08 | Denial of Service | mitigate | CLOSED | `backend/app/api/auth.py:75-95` — new-user path calls `db.add(user); db.commit(); db.refresh(user)` before token creation; existing-user path has exactly one `db.commit(); db.refresh(user)` with no redundant `db.add`; repeated calls produce exactly one user row |
| T-1-09 | Information Disclosure | accept | CLOSED | Accepted risk — see Accepted Risks log below |

---

## Accepted Risks Log

| Threat ID | Category | Risk Statement | Rationale | Owner | Review Date |
|-----------|----------|----------------|-----------|-------|-------------|
| T-1-07 | Information Disclosure | Orphaned pre-pivot files (`prophet_forecaster.py`, `forecast_tasks.py`, `data_pipeline.py`) existed on disk until plan 01-02 deleted them | Files referenced the deleted `Material` model and contained no secrets, credentials, or sensitive data. Risk is code hygiene / `ModuleNotFoundError` on import, not data exposure. Files were deleted as part of plan 01-02 scope, so the residual risk is zero at phase completion. Accepted at plan authoring time; deletion confirmed in 01-02-SUMMARY self-check. | Phase 01 executor | 2026-07-16 |
| T-1-09 | Information Disclosure | N+1 queries in `GET /cart` and `GET /components` | N+1 queries are a performance issue only. Each query is scoped by `current_user.id` (cart) or returns only public component catalogue fields (components). Neither query exposes data outside the authenticated user's authorization scope. The pattern was fixed as part of plan 01-03 for performance reasons; residual security risk remains accepted as non-existent. | Phase 01 executor | 2026-07-16 |

---

## Unregistered Threat Flags

None. All three SUMMARY files (`01-01-SUMMARY.md`, `01-02-SUMMARY.md`, `01-03-SUMMARY.md`) reported no new threat flags under `## Threat Flags`.

---

## Verification Commands

The following commands can be re-run at any time to confirm mitigations remain in place:

```bash
# T-1-01: SECRET_KEY validator present
grep -n 'field_validator' backend/app/core/config.py

# T-1-01: Known defaults blocked
python -c "
import os, sys
sys.path.insert(0, 'backend')
os.environ['SECRET_KEY'] = 'dev-secret-key-change-in-production'
from app.core.config import Settings
Settings(SECRET_KEY='dev-secret-key-change-in-production', _env_file=None)
" 2>&1 | grep -i 'insecure\|error'

# T-1-02: No wildcard CORS
grep -c 'allow_origins=\["\*"\]' backend/app/main.py   # must return 0

# T-1-03: DEBUG defaults False
grep 'DEBUG: bool' backend/app/core/config.py           # must show False

# T-1-04: Auth guards on live-prices (3 occurrences)
grep -c 'get_current_user' backend/app/api/live_prices.py           # >= 3

# T-1-04: Auth guards on market-intelligence (6 occurrences)
grep -c 'get_current_user' backend/app/api/market_intelligence.py   # >= 6

# T-1-05: No hardcoded SECRET_KEY in docker-compose
grep 'SECRET_KEY' docker-compose.yml   # must show only ${SECRET_KEY}

# T-1-06: No celery_worker service
grep -c 'celery_worker' docker-compose.yml   # must return 0

# T-1-08: demo_login new-user path has db.add
grep -A 15 'if not user:' backend/app/api/auth.py | grep 'db.add'

# Run full test suite
cd backend && python -m pytest tests/test_security_hardening.py tests/test_auth_guards.py tests/test_demo_login.py -v
```

---

## Notes

- ASVS Level 1 requirements verified. No Level 2 or Level 3 requirements were in scope for this phase.
- `block_on: high` — no open high-severity threats; phase is unblocked.
- Five pre-existing test failures in `test_sourcing.py` and `test_strategies.py` were observed during plan 01-02 verification and are unrelated to security. They are tracked in `.planning/phases/01-codebase-hardening/deferred-items.md`.
- The `celery_worker` service removal (T-1-05 secondary, T-1-06 primary) also resolved the hardcoded SECRET_KEY that appeared in the worker's `environment:` block, closing T-1-05 fully without a separate fix.
