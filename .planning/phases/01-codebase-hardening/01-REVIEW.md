---
phase: 01-codebase-hardening
reviewed: 2026-04-16T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - backend/.env.example
  - backend/app/api/auth.py
  - backend/app/api/cart.py
  - backend/app/api/components.py
  - backend/app/api/live_prices.py
  - backend/app/api/market_intelligence.py
  - backend/app/core/config.py
  - backend/app/main.py
  - backend/app/optimization/constants.py
  - backend/app/optimization/costs.py
  - backend/app/optimization/sourcing.py
  - backend/app/optimization/strategies.py
  - backend/tests/conftest.py
  - backend/tests/test_auth_guards.py
  - backend/tests/test_demo_login.py
  - backend/tests/test_security_hardening.py
  - docker-compose.yml
findings:
  critical: 2
  warning: 5
  info: 4
  total: 11
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-04-16
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

This review covers the codebase-hardening phase additions: security configuration, auth endpoints, cart and component APIs, live pricing and market intelligence modules, optimization core (constants, costs, sourcing, strategies), the test suite, and Docker Compose.

The hardening work is solid overall — `SECRET_KEY` validation at startup, scoped CORS origins, auth guards on live-price and market endpoints, and demo-login idempotency are all correctly implemented. The optimization layer (CP-SAT MILP, cost model, strategy weights) is well-structured with proper unit citations.

Two critical issues were found: hardcoded credentials in `docker-compose.yml` that will be committed to version control, and an information-disclosure bug in the `/live-prices/{mpn}/sync` endpoint that exposes whether the MPN exists in the DB to unauthenticated-adjacent paths. Five warnings cover logic gaps that can cause incorrect behavior at runtime. Four info items are code quality notes.

---

## Critical Issues

### CR-01: Hardcoded PostgreSQL credentials in docker-compose.yml

**File:** `docker-compose.yml:8-10`
**Issue:** The `db` service hard-codes `POSTGRES_PASSWORD: logistics_password` directly in the Compose file. This value is committed to version control and used as the actual database password in any environment where the Compose file is consumed without override. Anyone with access to the repo has the database credential.
**Fix:** Replace with an environment variable reference, consistent with how `SECRET_KEY` is already handled:
```yaml
db:
  image: postgres:16-alpine
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-logistics_user}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}   # no default — must be set in .env
    POSTGRES_DB: ${POSTGRES_DB:-logistics_db}
```
Add `POSTGRES_PASSWORD=` to `.env.example` with a generation hint. The `backend` service `DATABASE_URL` should be updated to match: `postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}`.

---

### CR-02: `/live-prices/{mpn}/sync` makes an internal unauthenticated call to `get_live_prices`

**File:** `backend/app/api/live_prices.py:276`
**Issue:** The `sync_component_prices` endpoint calls `await get_live_prices(mpn, current_user=current_user)` directly — bypassing FastAPI's dependency injection. While `current_user` is correctly threaded through, this internal call pattern skips the `db` parameter that `get_live_prices` would need if it were ever refactored to accept one. More concretely, the call on line 276 omits `include_unauthorized`, defaulting it to `True`, which means every sync operation silently includes gray-market offers regardless of what the calling user intended. Any future refactor that adds parameters to `get_live_prices` will silently break this path.

Additionally, if no API sources are configured (both code paths at lines 153-158 raise HTTP exceptions), calling `get_live_prices` from within `sync_component_prices` will raise an unhandled `HTTPException` inside the function body, which FastAPI will catch and return — but the 404/503 response body will be misleading ("No offers found for MPN") rather than a proper sync failure response.

**Fix:** Extract the offer-fetching logic into a non-HTTP helper function (e.g., `_fetch_live_offers(mpn, settings) -> List[Dict]`) and call that helper from both the HTTP endpoint and the sync endpoint. This removes the internal-call anti-pattern entirely:
```python
async def _fetch_live_offers(mpn: str) -> List[Dict]:
    """Core offer-fetching logic, shared by get_live_prices and sync_component_prices."""
    # ... same source iteration logic ...
    return merged

@router.get("/{mpn}", response_model=LivePriceResponse)
async def get_live_prices(mpn: str, ...):
    offers = await _fetch_live_offers(mpn)
    ...

@router.post("/{mpn}/sync")
async def sync_component_prices(mpn: str, ...):
    try:
        offers = await _fetch_live_offers(mpn)
    except HTTPException:
        return {"updated": 0, "message": "No live offers available"}
    ...
```

---

## Warnings

### WR-01: `filter_price_outliers` silently drops all offers for a component that has zero positive-priced offers

**File:** `backend/app/optimization/sourcing.py:107-110`
**Issue:** The outlier filter iterates `prices = [o.price_usd for o in group if o.price_usd > 0]`. If every offer for a component has `price_usd == 0` (e.g., a data ingestion error or a quote-only item), `prices` is empty, the `continue` is hit, and none of the offers are added to `kept`. The result is that the component disappears entirely from `offers_by_component`, triggering the `missing` check on line 200 with a `ValueError("No valid offers for components after filtering: ...")`. This is a silent data quality failure — the error message blames "filtering" without indicating that zero-price data was the cause, making debugging harder.
**Fix:** Log a warning when a component group is skipped due to all-zero prices, and include the cause in the `ValueError`:
```python
if not prices:
    logger.warning("component_id=%s has no offers with price > 0, skipping outlier filter", cid)
    # Still add the zero-price offers so the missing-check error is informative
    kept.extend(group)
    continue
```

---

### WR-02: Cart `add_to_cart` does not prevent duplicate entries for the same (user, component, distributor)

**File:** `backend/app/api/cart.py:114-123`
**Issue:** `add_to_cart` creates a new `CartItem` row every time it is called without checking whether the user already has that component-distributor combination in their cart. Repeated calls will create duplicate rows. The downstream optimizer (`solve.py`) likely iterates cart items and would process duplicates as separate demands, potentially over-ordering stock or creating solver infeasibility (sum of quantities might exceed stock). The stock check on line 107 uses `body.quantity` alone, not `existing_quantity + body.quantity`.
**Fix:** Query for an existing cart item before inserting, and either update quantity or return a 409:
```python
existing_item = db.query(CartItem).filter(
    CartItem.user_id == current_user.id,
    CartItem.component_id == body.component_id,
    CartItem.distributor_id == body.distributor_id,
).first()
if existing_item:
    raise HTTPException(
        status_code=409,
        detail="This component/distributor combination is already in your cart. Remove it first or update the quantity.",
    )
```

---

### WR-03: `solve_sourcing` is not guarded against empty `bom` input

**File:** `backend/app/optimization/sourcing.py:263`
**Issue:** `avg_demand = sum(b.quantity for b in bom) / max(len(bom), 1)` uses `max(len(bom), 1)` to avoid a `ZeroDivisionError`, but if `bom` is empty the function will also fail at line 200's missing-check loop — returning an empty `missing` list and proceeding to build an empty `CpModel` with no variables and no objective, which OR-Tools will mark `OPTIMAL` with zero cost. The resulting `SourcingResult` will have an empty `assignments` list and `total_component_cost=0`, silently succeeding with a no-op result rather than returning an error.
**Fix:** Add an explicit guard at the top of `solve_sourcing`:
```python
if not bom:
    raise ValueError("BOM is empty — cannot solve sourcing with zero components")
```

---

### WR-04: `config.py` `SECRET_KEY` default value passes its own validator

**File:** `backend/app/core/config.py:15`
**Issue:** The field default is `"your-secret-key-change-in-production"`, which is also in the `blocked` set on line 72. However, Pydantic v2 `BaseSettings` only runs `field_validator` when a value is explicitly assigned — it does **not** validate default values at class definition time. This means that if the `.env` file is absent and `SECRET_KEY` is not set in the environment, `settings.SECRET_KEY` will silently be `"your-secret-key-change-in-production"` — the exact insecure value the validator is supposed to block.

To reproduce: delete `.env`, start the server — it starts successfully with the weak default.
**Fix:** Remove the default entirely, making the field required, so startup fails with a clear config error when `SECRET_KEY` is unset:
```python
SECRET_KEY: str   # No default — must be set in environment
```
Alternatively keep the default but add a `model_validator(mode="after")` that calls `validate_secret_key(self.SECRET_KEY)` unconditionally.

---

### WR-05: `transit_days` returns `math.ceil` result but is declared as `-> float`

**File:** `backend/app/optimization/costs.py:72`
**Issue:** `math.ceil` in Python 3 returns an `int`, but the return type annotation is `float`. This is a minor type inconsistency, but it means callers that rely on the `float` annotation (e.g., `leg_lead_time_days` which adds `handling: int` to the result) will get an `int` sum, not a `float`. In the ML feature engineering (`build_feature_row`) and any downstream comparison with a float threshold this may cause subtle type-check failures with strict type checkers or Pydantic serialization.
**Fix:** Either change the return annotation to `int` (which is the true return type) or add an explicit `float()` cast:
```python
def transit_days(distance_km: float) -> int:
    return math.ceil(distance_km / GROUND_KM_PER_DAY)
```

---

## Info

### IN-01: `components.py` public endpoints have no authentication requirement

**File:** `backend/app/api/components.py:64-269`
**Issue:** All component listing endpoints (`GET /components`, `GET /components/categories`, `GET /components/manufacturers`, `GET /components/stats`, `GET /components/{id}`, `GET /components/{id}/offers`) have no `current_user` dependency. This is likely intentional for a catalog-browsing UX, but it means the 791-component catalog and all offer pricing data (real competitive prices, stock levels, distributor locations) are accessible without any authentication. This is worth a conscious decision in the team — if this is intentional for a demo product, it should be documented.

---

### IN-02: `conftest.py` test database file is not cleaned up on process exit

**File:** `backend/tests/conftest.py:26`
**Issue:** `TEST_DB_URL = "sqlite:///./test_hardening.db"` creates a file on disk. The `db_session` fixture calls `drop_all` after each test, but the SQLite file itself (an empty schema) is left on disk. This is a minor leftover artifact that can accumulate across CI runs. The file path is relative to the current working directory at test invocation, which may not always be `backend/`.
**Fix:** Use an in-memory SQLite database in tests:
```python
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
```

---

### IN-03: `live_prices.py` `get_bom_prices` creates a new `NexarClient` instance per MPN in the fallback path

**File:** `backend/app/api/live_prices.py:218-224`
**Issue:** Inside the per-MPN loop (lines 212-248), when a Nexar bulk result is available (`if mpn in nexar_parts`), the code instantiates a new `NexarClient` object on line 219 solely to call `client.parse_offers()`. `parse_offers` is a pure parsing method with no network I/O, but the client constructor may acquire an OAuth token or set up HTTP sessions depending on implementation. Instantiating one client per MPN is wasteful — this should reuse the client created in the bulk-fetch block above.

---

### IN-04: `docker-compose.yml` runs `uvicorn` with `--reload` in production Compose

**File:** `docker-compose.yml:49`
**Issue:** The backend service command is `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`. The `--reload` flag is a development convenience that polls the filesystem and restarts the process on file changes. In production this has two downsides: (a) it adds unnecessary CPU overhead from filesystem watching, and (b) it exposes the process to a restart attack if the mounted `./backend/app` volume is writable by a low-privilege process.
**Fix:** Either remove `--reload` from the Compose command, or split into separate `docker-compose.yml` (production) and `docker-compose.override.yml` (development) files where the override adds `--reload`.

---

_Reviewed: 2026-04-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
