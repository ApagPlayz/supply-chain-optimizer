# Phase 1: Codebase Hardening - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Eliminate all security vulnerabilities and orphaned pre-pivot artifacts so the codebase is safe to share publicly and demo. No new features. No frontend changes. Pure backend hardening: secret key validation, CORS restriction, DEBUG default, auth guards on unauthenticated endpoints, orphaned file removal, and demo login bug fix.

</domain>

<decisions>
## Implementation Decisions

### Orphaned files (HARD-05)
- **D-01:** Delete all 3 orphaned files: `backend/app/ml/prophet_forecaster.py`, `backend/app/ml/forecast_tasks.py`, `backend/app/scrapers/data_pipeline.py`
- **D-02:** Phase 5 will write a new `prophet_forecaster.py` from scratch targeting `Component`/`DistributorOffer` — no stubbing needed
- **D-03:** Also remove the `celery_worker` service from `docker-compose.yml` if it depends solely on the deleted `forecast_tasks.py`

### CORS configuration (HARD-02)
- **D-04:** Add `ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"` to `Settings` in `config.py`
- **D-05:** Parse as comma-separated list: `[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]`
- **D-06:** When `DEBUG=True`, automatically include `http://localhost:5173` and `http://localhost:3000` in the allowed origins list even if ALLOWED_ORIGINS is overridden — preserves local dev experience
- **D-07:** In production (`DEBUG=False`), ALLOWED_ORIGINS must be explicitly set in `.env`; the default localhost values are not served

### SECRET_KEY validation (HARD-01)
- **D-08:** Raise `ValueError` at startup (on `Settings` instantiation via Pydantic validator) if `SECRET_KEY` matches any of: `"your-secret-key-change-in-production"`, `"dev-secret-key-change-in-production"`, `"secret"`, `"changeme"`, or any value shorter than 32 characters
- **D-09:** Error message must include instructions: `"Set SECRET_KEY in .env to a random 64-char string: python -c 'import secrets; print(secrets.token_hex(32))'"`

### DEBUG default (HARD-03)
- **D-10:** Change `DEBUG: bool = True` to `DEBUG: bool = False` in `Settings`
- **D-11:** Update `.env.example` (or create one) documenting `DEBUG=true` as a dev override
- **D-12:** SQLAlchemy `echo=settings.DEBUG` in `database.py` — no change needed, already conditional

### Auth guards (HARD-04)
- **D-13:** Add `current_user: User = Depends(get_current_user)` to all route functions in `backend/app/api/live_prices.py` and `backend/app/api/market_intelligence.py`
- **D-14:** No frontend currently calls these endpoints (confirmed by grep) — adding auth will not break any existing page

### Demo login bug (HARD-06)
- **D-15:** In `auth.py` demo_login, the `else` branch has duplicate: `db.commit()` → `db.refresh(user)` → `db.add(user)` → `db.commit()` → `db.refresh(user)`. Fix: remove the redundant `db.add(user)` and second `db.commit()` + `db.refresh(user)` after the first commit cycle
- **D-16:** The `if not user:` (new user) branch also has a bug: creates `User(...)` but never calls `db.add(user)` or `db.commit()` — user is never persisted. Fix: add `db.add(user); db.commit(); db.refresh(user)` in the new-user branch

### Debt scope (Plan 01-03)
- **D-17:** Fix demo login bugs (D-15, D-16) — highest priority
- **D-18:** Fix N+1 queries in `/cart` and `/components` endpoints — affects demo performance
- **D-19:** Skip FK constraints, unique constraints, and unseeded Monte Carlo — these belong in Phase 2 (schema work) and the optimizer improvement scope

### Claude's Discretion
- Exact `.env.example` format and which keys to document
- Whether to add a startup banner logging security configuration state (e.g., "Running with DEBUG=False, CORS=[...]")
- N+1 fix implementation approach (selectinload vs. joinedload)

</decisions>

<specifics>
## Specific Ideas

- Secret key validation should include the generation command in the error message — copy-paste friendly for anyone who clones the repo
- Demo login is used heavily for portfolio demos — must work reliably on repeated calls including concurrent calls

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Security issues (exact file:line locations)
- `backend/app/core/config.py:14` — SECRET_KEY default value to replace with validator
- `backend/app/core/config.py:19` — DEBUG: bool = True to change to False
- `backend/app/main.py:56` — allow_origins=["*"] CORS wildcard to fix
- `backend/app/api/auth.py:84-93` — demo login duplicate db.add bug (both new-user and existing-user paths)
- `backend/app/api/live_prices.py` — all route functions need Depends(get_current_user)
- `backend/app/api/market_intelligence.py` — all route functions need Depends(get_current_user)

### Orphaned files to delete
- `backend/app/ml/prophet_forecaster.py` — delete entirely
- `backend/app/ml/forecast_tasks.py` — delete entirely
- `backend/app/scrapers/data_pipeline.py` — delete entirely

### Project requirements
- `.planning/REQUIREMENTS.md` — HARD-01 through HARD-06 requirement definitions
- `.planning/codebase/CONCERNS.md` — Full detail on all critical issues and technical debt

### Patterns to follow
- `backend/app/api/cart.py` — Example of authenticated endpoint using `Depends(get_current_user)` pattern
- `backend/app/api/components.py` — Another authenticated endpoint pattern
- `backend/app/core/config.py` — Settings class to add ALLOWED_ORIGINS field and SECRET_KEY validator

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `get_current_user` dependency in `backend/app/api/auth.py:16-29` — already written, just needs adding to live_prices + market_intelligence routes
- `HTTPBearer` security scheme already configured in auth.py — no new setup needed

### Established Patterns
- All protected endpoints use `current_user: User = Depends(get_current_user)` — e.g., cart.py, components.py
- Pydantic v2 Settings with `class Config: env_file = ".env"` — validator should use `@field_validator` or `@model_validator` (Pydantic v2 style)

### Integration Points
- `backend/app/core/config.py` — central settings, all fixes touch this file
- `backend/app/main.py` — CORS middleware reads from settings
- `backend/app/api/auth.py` — demo login fix + get_current_user lives here

</code_context>

<deferred>
## Deferred Ideas

- FK constraints on DistributorOffer and CartItem — Phase 2 adds new tables anyway, do schema work together
- Unique constraint on DistributorOffer(component_id, distributor_id) — Phase 2 scope
- Unseeded Monte Carlo in solve.py — Phase 2 (graph + benchmark work touches solve.py)
- ML lead time hardcoded category bug in solve.py — Phase 2 scope

</deferred>

---

*Phase: 01-codebase-hardening*
*Context gathered: 2026-04-15*
