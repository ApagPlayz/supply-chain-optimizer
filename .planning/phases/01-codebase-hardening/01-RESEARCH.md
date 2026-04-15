# Phase 1: Codebase Hardening - Research

**Researched:** 2026-04-15
**Domain:** FastAPI security hardening, orphaned code removal, SQLAlchemy query optimization
**Confidence:** HIGH

## Summary

Phase 1 is a pure backend hardening phase with no new features. Every change touches well-understood FastAPI/Pydantic/SQLAlchemy patterns. The codebase has been fully inspected: all six issues (SECRET_KEY default, CORS wildcard, DEBUG=True, unguarded endpoints, orphaned pre-pivot files, demo login bug) are confirmed present at the exact file:line locations documented in CONTEXT.md.

The hardest part is the orphaned file removal chain: deleting 3 files (`prophet_forecaster.py`, `forecast_tasks.py`, `data_pipeline.py`) also requires updating `celery_app.py` (which imports them) and removing the `celery_worker` service from `docker-compose.yml`. The N+1 query in `cart.py:get_cart` is a textbook case -- a loop issuing 2 queries per cart item -- fixable with a single joined query or `selectinload`.

**Primary recommendation:** Execute security fixes first (SECRET_KEY, CORS, DEBUG, auth guards), then orphaned file deletion (including celery_app.py cleanup), then bug fixes and query optimization. All changes are isolated to backend Python files.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Delete all 3 orphaned files: `backend/app/ml/prophet_forecaster.py`, `backend/app/ml/forecast_tasks.py`, `backend/app/scrapers/data_pipeline.py`
- **D-02:** Phase 5 will write a new `prophet_forecaster.py` from scratch targeting `Component`/`DistributorOffer` -- no stubbing needed
- **D-03:** Also remove the `celery_worker` service from `docker-compose.yml` if it depends solely on the deleted `forecast_tasks.py`
- **D-04:** Add `ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"` to `Settings` in `config.py`
- **D-05:** Parse as comma-separated list: `[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]`
- **D-06:** When `DEBUG=True`, automatically include `http://localhost:5173` and `http://localhost:3000` in the allowed origins list even if ALLOWED_ORIGINS is overridden
- **D-07:** In production (`DEBUG=False`), ALLOWED_ORIGINS must be explicitly set in `.env`; the default localhost values are not served
- **D-08:** Raise `ValueError` at startup (on `Settings` instantiation via Pydantic validator) if `SECRET_KEY` matches any of: `"your-secret-key-change-in-production"`, `"dev-secret-key-change-in-production"`, `"secret"`, `"changeme"`, or any value shorter than 32 characters
- **D-09:** Error message must include instructions: `"Set SECRET_KEY in .env to a random 64-char string: python -c 'import secrets; print(secrets.token_hex(32))'"`
- **D-10:** Change `DEBUG: bool = True` to `DEBUG: bool = False` in `Settings`
- **D-11:** Update `.env.example` (or create one) documenting `DEBUG=true` as a dev override
- **D-12:** SQLAlchemy `echo=settings.DEBUG` in `database.py` -- no change needed, already conditional
- **D-13:** Add `current_user: User = Depends(get_current_user)` to all route functions in `backend/app/api/live_prices.py` and `backend/app/api/market_intelligence.py`
- **D-14:** No frontend currently calls these endpoints (confirmed by grep) -- adding auth will not break any existing page
- **D-15:** In `auth.py` demo_login, the `else` branch has duplicate: `db.commit()` -> `db.refresh(user)` -> `db.add(user)` -> `db.commit()` -> `db.refresh(user)`. Fix: remove the redundant `db.add(user)` and second `db.commit()` + `db.refresh(user)` after the first commit cycle
- **D-16:** The `if not user:` (new user) branch also has a bug: creates `User(...)` but never calls `db.add(user)` or `db.commit()` -- user is never persisted. Fix: add `db.add(user); db.commit(); db.refresh(user)` in the new-user branch
- **D-17:** Fix demo login bugs (D-15, D-16) -- highest priority
- **D-18:** Fix N+1 queries in `/cart` and `/components` endpoints -- affects demo performance
- **D-19:** Skip FK constraints, unique constraints, and unseeded Monte Carlo -- these belong in Phase 2

### Claude's Discretion
- Exact `.env.example` format and which keys to document
- Whether to add a startup banner logging security configuration state (e.g., "Running with DEBUG=False, CORS=[...]")
- N+1 fix implementation approach (selectinload vs. joinedload)

### Deferred Ideas (OUT OF SCOPE)
- FK constraints on DistributorOffer and CartItem -- Phase 2
- Unique constraint on DistributorOffer(component_id, distributor_id) -- Phase 2
- Unseeded Monte Carlo in solve.py -- Phase 2
- ML lead time hardcoded category bug in solve.py -- Phase 2
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-01 | SECRET_KEY raises ValueError at startup if it matches the default dev value | Pydantic v2 `@field_validator` on Settings class; exact blocklist and length check confirmed in D-08 |
| HARD-02 | CORS allow_origins restricted to frontend domain via env var (not wildcard) | `main.py:56` currently has `allow_origins=["*"]`; replace with parsed ALLOWED_ORIGINS from Settings |
| HARD-03 | DEBUG defaults to False; stack traces not exposed in production responses | `config.py:19` currently `DEBUG: bool = True`; change default to False; FastAPI debug flag already reads this |
| HARD-04 | Live pricing and market intelligence endpoints require authentication | 8 route functions across 2 files need `Depends(get_current_user)` added |
| HARD-05 | Orphaned pre-pivot files removed or ported | 3 files to delete + celery_app.py include list + docker-compose celery_worker service |
| HARD-06 | Demo login duplicate db.add bug fixed | Two bugs in auth.py:70-95: new-user path never persists, existing-user path has redundant db.add |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Backend:** Python 3.11+ / FastAPI / SQLAlchemy / Pydantic v2 / SQLite for dev
- **Authentication:** JWT tokens via python-jose + passlib (pbkdf2_sha256)
- **All data must be real** -- no synthetic data
- **Testing workflow:** Login -> Dashboard -> Map -> Scheduler -> Cart -> Checkout -> Digital Twin
- **Docker Compose** used for prod with PostgreSQL + Redis
- **No frontend changes** in this phase (CONTEXT.md: "Pure backend hardening")

## Standard Stack

### Core (Already Installed -- No New Dependencies)

| Library | Version | Purpose | Verified |
|---------|---------|---------|----------|
| fastapi | 0.135.3 | Web framework, CORS middleware | [VERIFIED: pip show] |
| pydantic | 2.12.5 | Data validation, Settings model | [VERIFIED: pip show] |
| pydantic-settings | 2.13.1 | BaseSettings with .env loading | [VERIFIED: pip show] |
| sqlalchemy | 2.0.49 | ORM, query optimization | [VERIFIED: pip show] |
| python-jose | installed | JWT encode/decode | [VERIFIED: security.py imports] |
| pytest | 9.0.2 | Test framework | [VERIFIED: pip show] |
| httpx | 0.28.1 | Async test client for FastAPI | [VERIFIED: pip show] |

**No new packages needed.** All changes use existing installed libraries.

## Architecture Patterns

### Pattern 1: Pydantic v2 Field Validator for SECRET_KEY

**What:** Use `@field_validator` (Pydantic v2 style) to validate SECRET_KEY at Settings instantiation time.
**Why not `@validator`:** The `@validator` decorator is Pydantic v1 and deprecated in v2. This project uses pydantic 2.12.5. [VERIFIED: pip show pydantic]
**When to use:** Immediately when `Settings()` is constructed at module level in `config.py:68`.

```python
# Source: Pydantic v2 docs — field validators
from pydantic import field_validator

class Settings(BaseSettings):
    SECRET_KEY: str = "your-secret-key-change-in-production"
    # ...

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        blocked = {
            "your-secret-key-change-in-production",
            "dev-secret-key-change-in-production",
            "secret",
            "changeme",
        }
        if v in blocked or len(v) < 32:
            raise ValueError(
                "SECRET_KEY is insecure. "
                "Set SECRET_KEY in .env to a random 64-char string: "
                "python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return v
```
[VERIFIED: Pydantic v2 uses `@field_validator` with `@classmethod`] [CITED: pydantic docs field-validators]

**Critical note:** The validator fires when `settings = Settings()` executes at `config.py:68`. Because `main.py` imports `settings` at the module level, a bad SECRET_KEY will crash the server at startup before any request is served. This is the desired behavior per HARD-01.

**Critical note 2:** The `.env` file at `backend/.env` likely contains `SECRET_KEY=your-secret-key-change-in-production`. The developer MUST update their `.env` file before the server will start after this change. The error message includes the generation command for convenience.

### Pattern 2: CORS Origin Parsing with DEBUG Fallback

**What:** Parse `ALLOWED_ORIGINS` as comma-separated string, auto-include localhost origins when DEBUG=True.
**When to use:** In `main.py` when constructing the CORS middleware.

```python
# In config.py
ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

# In main.py
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if settings.DEBUG:
    dev_origins = {"http://localhost:5173", "http://localhost:3000"}
    origins = list(set(origins) | dev_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
[ASSUMED: This pattern follows FastAPI CORS middleware docs; the specific DEBUG-conditional logic is project-specific per D-06/D-07]

**Ordering concern:** `settings.DEBUG` defaults to `False` after D-10. In production, if `ALLOWED_ORIGINS` is left at its default, localhost origins will NOT be included (correct). The developer must set `DEBUG=true` in `.env` for local dev.

### Pattern 3: Auth Guard Addition

**What:** Add `current_user: User = Depends(get_current_user)` to endpoint function signatures.
**Files:** `live_prices.py` (3 routes) and `market_intelligence.py` (5 routes, but `/status` may stay public).

```python
from app.api.auth import get_current_user
from app.models.user import User

@router.get("/{mpn}", response_model=LivePriceResponse)
async def get_live_prices(
    mpn: str,
    include_unauthorized: bool = Query(True),
    current_user: User = Depends(get_current_user),  # ADD THIS
):
```
[VERIFIED: This exact pattern is used in cart.py and components.py endpoints already]

**Endpoint inventory for auth guards:**

`live_prices.py`:
1. `GET /{mpn}` -- `get_live_prices` -- needs auth
2. `POST /bom` -- `get_bom_prices` -- needs auth
3. `POST /{mpn}/sync` -- `sync_component_prices` -- needs auth (already has `db: Session = Depends(get_db)`)

`market_intelligence.py`:
1. `GET /summary` -- `get_market_summary` -- needs auth
2. `GET /disruption-index` -- `get_disruption_index` -- needs auth
3. `GET /alerts` -- `get_disruption_alerts` -- needs auth
4. `GET /commodities` -- `get_commodity_prices` -- needs auth
5. `GET /trade-policy` -- `get_trade_policy` -- needs auth
6. `GET /status` -- `get_api_status` -- DECISION NEEDED: This only shows which APIs are configured (no secrets exposed). Could stay public for health checks. Recommend adding auth to be safe.

### Pattern 4: Demo Login Fix

**What:** Fix both branches of the demo_login function.
**Current bugs (confirmed by code inspection):**

Bug 1 -- New user path (line 76-83): Creates `User(...)` object but never calls `db.add(user)` or `db.commit()`. The user is never persisted. The JWT token is created with `user.id` which is `None` (SQLAlchemy default for un-flushed objects), causing a broken token.

Bug 2 -- Existing user path (line 84-93): After `db.commit(); db.refresh(user)`, the code calls `db.add(user)` again on an already-persisted object, then commits again. On SQLite this is a no-op (SQLAlchemy recognizes the object is already in the session), but it is wasteful and confusing. The `db.add(user)` on an existing row in SQLAlchemy does NOT insert a duplicate -- it attaches/merges. So the actual failure mode is the new-user path, not the existing-user path.

[VERIFIED: Read auth.py:69-95, confirmed both bugs present]

```python
@router.post("/demo", response_model=TokenResponse)
def demo_login(db: Session = Depends(get_db)):
    demo_email = "demo@example.com"
    user = db.query(User).filter(User.email == demo_email).first()

    if not user:
        user = User(
            email=demo_email,
            password_hash=get_password_hash("demo"),
            factory_name="Greenville Advanced Manufacturing",
            latitude=34.8526,
            longitude=-82.3940,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.factory_name = "Greenville Advanced Manufacturing"
        user.latitude = 34.8526
        user.longitude = -82.3940
        db.commit()
        db.refresh(user)

    return {"access_token": create_access_token({"sub": str(user.id)})}
```

### Pattern 5: N+1 Query Fix in cart.py

**What:** Replace per-item queries in `get_cart` with a single joined query.
**Current problem (confirmed):** `cart.py:47-66` -- for each cart item, issues 2 separate queries (one for Component, one for Distributor). With 10 items in cart = 21 queries total.

**Recommended approach: joinedload (single query)**

```python
from sqlalchemy.orm import joinedload

# Option A: Use relationship-based eager loading (requires adding relationships to CartItem model)
# Option B: Use a manual join (no model change needed)

# Option B (recommended -- no model change, explicit):
items_raw = (
    db.query(CartItem, Component, Distributor)
    .join(Component, CartItem.component_id == Component.id)
    .join(Distributor, CartItem.distributor_id == Distributor.id)
    .filter(CartItem.user_id == current_user.id)
    .all()
)
results = [
    CartItemResponse(
        id=item.id,
        component_id=item.component_id,
        distributor_id=item.distributor_id,
        quantity=item.quantity,
        unit_price=item.unit_price,
        mpn=comp.mpn,
        manufacturer=comp.manufacturer,
        category=comp.category,
        distributor_name=dist.name,
        distributor_city=dist.city,
        distributor_state=dist.state,
        distributor_country=dist.country,
        created_at=item.created_at,
    )
    for item, comp, dist in items_raw
]
```
[VERIFIED: CartItem model has no SQLAlchemy relationships defined -- component_id and distributor_id are plain Integer columns without ForeignKey constraints to Component/Distributor. Manual join is the correct approach.]

**Note:** `CartItem.component_id` has `ForeignKey("users.id")` for user_id but NOT for component_id or distributor_id. D-19 defers FK constraints to Phase 2. The manual join still works because the data is consistent (seeded from the same pipeline).

### Pattern 6: N+1 Query Fix in components.py

**What:** Replace per-component offer queries in `list_components` with aggregated subquery.
**Current problem (confirmed):** `components.py:89-106` -- for each of up to 1000 components, queries all offers. With 791 components = 792 queries.

```python
from sqlalchemy import func as sqla_func
from sqlalchemy.orm import aliased

# Use subquery aggregation
offer_stats = (
    db.query(
        DistributorOffer.component_id,
        sqla_func.min(DistributorOffer.price).label("min_price"),
        sqla_func.max(DistributorOffer.price).label("max_price"),
        sqla_func.count(DistributorOffer.id).label("num_offers"),
    )
    .filter(DistributorOffer.price > 0)
    .group_by(DistributorOffer.component_id)
    .subquery()
)

q = (
    db.query(Component, offer_stats.c.min_price, offer_stats.c.max_price, offer_stats.c.num_offers)
    .outerjoin(offer_stats, Component.id == offer_stats.c.component_id)
)
# ... apply filters, offset, limit
```
[ASSUMED: Standard SQLAlchemy subquery pattern; specific implementation will need testing]

### Anti-Patterns to Avoid
- **DO NOT use `@validator` (Pydantic v1):** This project uses Pydantic v2.12.5. Use `@field_validator` with `@classmethod`.
- **DO NOT add SQLAlchemy relationships to CartItem for FK-less columns:** The CartItem model has plain Integer columns for component_id and distributor_id without ForeignKey declarations. Adding `relationship()` without FK will fail. Use manual joins instead.
- **DO NOT use `allow_origins=["*"]` with `allow_credentials=True`:** Browsers reject this combination per the CORS spec. The current code has this exact antipattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Secret key validation | Custom startup check script | Pydantic `@field_validator` | Fires automatically on Settings instantiation; impossible to bypass |
| CORS origin parsing | Manual middleware | FastAPI `CORSMiddleware` with parsed list | Well-tested, handles preflight OPTIONS correctly |
| Auth dependency injection | Manual token parsing in each route | `Depends(get_current_user)` | Already implemented in auth.py; tested in cart.py and other endpoints |
| N+1 query resolution | Custom caching layer | SQLAlchemy JOIN / subquery | Database handles this correctly; caching adds complexity |

## Common Pitfalls

### Pitfall 1: SECRET_KEY Validator Blocks Local Dev
**What goes wrong:** After adding the validator, `python -m uvicorn app.main:app` crashes because `.env` still has the default key.
**Why it happens:** The validator runs at import time when `settings = Settings()` executes.
**How to avoid:** Update `.env` AND `.env.example` in the same commit. Include clear error message with key generation command.
**Warning signs:** Server refuses to start with no obvious error (the ValueError may be swallowed by some process managers).

### Pitfall 2: docker-compose.yml Still Has Default SECRET_KEY
**What goes wrong:** The `docker-compose.yml` backend service has `SECRET_KEY: dev-secret-key-change-in-production` hardcoded in `environment:` block (line ~39). After adding the validator, `docker-compose up` will crash.
**Why it happens:** Docker env vars override `.env` file.
**How to avoid:** Change docker-compose.yml to use a long random key or reference a `.env` file. Also the `celery_worker` service has the same key (line ~54).
**Warning signs:** Docker backend container exits immediately.

### Pitfall 3: Celery App Import Chain
**What goes wrong:** Deleting `forecast_tasks.py` and `data_pipeline.py` without updating `celery_app.py` causes `ImportError` on celery worker startup.
**Why it happens:** `celery_app.py:10` has `include=["app.scrapers.data_pipeline", "app.ml.forecast_tasks"]`.
**How to avoid:** Update `celery_app.py` include list in the same commit as file deletions. Since the celery_worker docker service is also being removed, clean up the whole chain.

### Pitfall 4: Demo Login Token with None User ID
**What goes wrong:** New demo user path creates User but never persists it. `user.id` is None. Token is created with `sub: "None"`. Later `decode_token` tries `int("None")` and fails.
**Why it happens:** Missing `db.add(user)` in the if-not-user branch.
**How to avoid:** This is exactly what D-16 fixes. Ensure both branches end with a committed, refreshed user before creating the token.

### Pitfall 5: CORS `allow_origins=["*"]` with `allow_credentials=True`
**What goes wrong:** Per the CORS spec, browsers MUST reject responses with `Access-Control-Allow-Origin: *` when credentials (cookies/auth headers) are included. Some browsers silently fail.
**Why it happens:** The current code has exactly this configuration at `main.py:54-60`.
**How to avoid:** Replace `["*"]` with explicit origin list. This is what HARD-02 fixes.

## Code Examples

### Complete config.py After Hardening

```python
# Source: Confirmed from reading config.py + Pydantic v2 docs
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./supply_chain.db"
    REDIS_URL: str = "redis://localhost:6379"

    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    DEBUG: bool = False  # D-10: changed from True
    PROJECT_NAME: str = "Supply Chain Intelligence Platform"
    API_V1_STR: str = "/api/v1"

    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"  # D-04

    # ... (other keys unchanged)

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        blocked = {
            "your-secret-key-change-in-production",
            "dev-secret-key-change-in-production",
            "secret",
            "changeme",
        }
        if v in blocked or len(v) < 32:
            raise ValueError(
                "SECRET_KEY is insecure. "
                "Set SECRET_KEY in .env to a random 64-char string: "
                "python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True
```

### Complete main.py CORS Section After Hardening

```python
# Source: Confirmed from reading main.py + FastAPI CORS docs
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if settings.DEBUG:
    dev_origins = {"http://localhost:5173", "http://localhost:3000"}
    origins = list(set(origins) | dev_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `backend/tests/conftest.py` (path setup only) |
| Quick run command | `cd backend && python -m pytest tests/ -x -q` |
| Full suite command | `cd backend && python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARD-01 | SECRET_KEY validator rejects defaults and short keys | unit | `pytest tests/test_security_hardening.py::test_secret_key_validation -x` | Wave 0 |
| HARD-02 | CORS origins parsed from env, not wildcard | unit | `pytest tests/test_security_hardening.py::test_cors_origins -x` | Wave 0 |
| HARD-03 | DEBUG defaults to False | unit | `pytest tests/test_security_hardening.py::test_debug_default -x` | Wave 0 |
| HARD-04 | Live-price and market endpoints return 401 without token | integration | `pytest tests/test_auth_guards.py -x` | Wave 0 |
| HARD-05 | No ModuleNotFoundError when importing backend | smoke | `python -c "import app.main"` | manual |
| HARD-06 | Demo login works on repeated calls | integration | `pytest tests/test_demo_login.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd backend && python -m pytest tests/ -x -q`
- **Per wave merge:** `cd backend && python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_security_hardening.py` -- covers HARD-01, HARD-02, HARD-03
- [ ] `tests/test_auth_guards.py` -- covers HARD-04 (401 on unauthenticated live-price/market calls)
- [ ] `tests/test_demo_login.py` -- covers HARD-06 (idempotent demo login, both new and existing user paths)
- [ ] Update `tests/conftest.py` -- add FastAPI TestClient fixture, test database setup, auth token helper

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | JWT via python-jose; SECRET_KEY hardening (HARD-01) |
| V3 Session Management | yes | Token expiry via ACCESS_TOKEN_EXPIRE_MINUTES; no session state |
| V4 Access Control | yes | `Depends(get_current_user)` on all sensitive endpoints (HARD-04) |
| V5 Input Validation | yes | Pydantic v2 request models (already in place) |
| V6 Cryptography | yes | SECRET_KEY minimum 32 chars; HS256 JWT signing |

### Known Threat Patterns for FastAPI + JWT

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| JWT forgery via default SECRET_KEY | Spoofing | HARD-01: reject known defaults at startup |
| CORS wildcard with credentials | Information Disclosure | HARD-02: explicit origin whitelist |
| Stack trace exposure in production | Information Disclosure | HARD-03: DEBUG=False default |
| Unauthenticated API access | Elevation of Privilege | HARD-04: auth guards on all sensitive endpoints |
| Race condition in demo login | Denial of Service | HARD-06: idempotent upsert pattern |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | N+1 fix using subquery aggregation in list_components will perform well with 791 components | Architecture Patterns / Pattern 6 | Low -- 791 rows is trivial for SQLite; fallback is the existing per-row approach |
| A2 | `/market/status` endpoint should also get auth guard | Architecture Patterns / Pattern 3 | Low -- worst case is one extra public endpoint that only shows config status |
| A3 | Removing celery_worker from docker-compose.yml has no other dependencies | Common Pitfalls | Low -- celery_worker only referenced `forecast_tasks` and `data_pipeline` |

## Open Questions

1. **docker-compose.yml SECRET_KEY**
   - What we know: docker-compose.yml has `SECRET_KEY: dev-secret-key-change-in-production` in both backend and celery_worker environment blocks
   - What's unclear: Should docker-compose.yml reference a `.env` file instead of hardcoding the key?
   - Recommendation: Replace hardcoded SECRET_KEY with `${SECRET_KEY}` env var reference, and document in `.env.example`

2. **CORS production origins**
   - What we know: Default ALLOWED_ORIGINS will be localhost URLs (for dev). In production, D-07 says the default localhost values should not be served.
   - What's unclear: The current default `"http://localhost:5173,http://localhost:3000"` will still be parsed even in production unless overridden.
   - Recommendation: When `DEBUG=False` and `ALLOWED_ORIGINS` is the default value, log a warning that CORS origins should be explicitly configured.

3. **celery_app.py: delete or update?**
   - What we know: `celery_app.py` references both deleted files in its `include` list and beat schedule. The celery_worker docker service is being removed.
   - What's unclear: Whether celery_app.py should be deleted entirely or kept as infrastructure for Phase 5 (Prophet resurrection).
   - Recommendation: Delete `celery_app.py` entirely. Phase 5 will build a new scheduled task system (possibly APScheduler, per MLOPS-01 in requirements). Keeping an orphaned celery_app.py adds confusion.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All backend code | Yes | 3.13 (venv) | -- |
| pytest | Test validation | Yes | 9.0.2 | -- |
| httpx | FastAPI TestClient | Yes | 0.28.1 | -- |
| SQLite | Dev database | Yes | built-in | -- |

No missing dependencies. All changes use existing installed packages.

## Sources

### Primary (HIGH confidence)
- `backend/app/core/config.py` -- read in full, Settings class with SECRET_KEY default confirmed
- `backend/app/main.py` -- read in full, CORS wildcard confirmed at line 56
- `backend/app/api/auth.py` -- read in full, demo_login bugs confirmed at lines 69-95
- `backend/app/api/cart.py` -- read in full, N+1 query confirmed at lines 47-66
- `backend/app/api/components.py` -- read in full, N+1 query confirmed at lines 89-106
- `backend/app/api/live_prices.py` -- read in full, 3 unguarded route functions confirmed
- `backend/app/api/market_intelligence.py` -- read in full, 6 unguarded route functions confirmed
- `backend/app/core/celery_app.py` -- read in full, orphaned imports confirmed at line 10
- `backend/app/core/security.py` -- read in full, JWT implementation confirmed
- `docker-compose.yml` -- read in full, celery_worker service and hardcoded SECRET_KEY confirmed
- `pip show pydantic pydantic-settings fastapi sqlalchemy pytest httpx` -- all versions verified

### Secondary (MEDIUM confidence)
- Pydantic v2 `@field_validator` syntax -- standard documented pattern [CITED: pydantic docs]
- FastAPI CORS middleware usage -- standard documented pattern [CITED: fastapi docs]

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all packages verified via pip, no new dependencies
- Architecture: HIGH -- all code read, all bugs confirmed at exact lines, patterns are standard FastAPI/Pydantic/SQLAlchemy
- Pitfalls: HIGH -- all pitfalls verified by reading actual source files

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (stable -- no fast-moving dependencies)
