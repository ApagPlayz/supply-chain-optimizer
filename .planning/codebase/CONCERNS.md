# Concerns
_Last updated: 2026-04-15_

## Summary

The codebase is in an active data pivot from synthetic materials to real electronic components data, leaving several orphaned pre-pivot artifacts that reference a `material` model that no longer exists. Security defaults are production-unsafe (wildcard CORS, hardcoded secret keys, unprotected demo endpoint), and all API endpoints related to live pricing and market intelligence are unauthenticated. No application-level tests exist for API routes, and several performance anti-patterns (N+1 queries) are present in heavily-used endpoints.

---

## Critical Issues

### 1. Hardcoded Default Secret Key
- Issue: `SECRET_KEY` defaults to `"your-secret-key-change-in-production"` in `config.py`, and `docker-compose.yml` uses `"dev-secret-key-change-in-production"`. If deployed without an explicit env override, JWTs are signed with a known key.
- Files: `backend/app/core/config.py:14`, `docker-compose.yml:39`, `docker-compose.yml:52`
- Impact: An attacker can forge valid JWT tokens for any user ID.
- Fix: Require `SECRET_KEY` at startup; raise a `ValueError` if it matches the default.

### 2. Wildcard CORS in Production
- Issue: `allow_origins=["*"]` in `main.py` permits cross-origin requests from any domain, including malicious third-party sites.
- Files: `backend/app/main.py:56`
- Impact: Enables CSRF-style attacks against authenticated users; credential cookies can be sent cross-origin.
- Fix: Restrict `allow_origins` to the actual frontend domain(s) via an env var.

### 3. DEBUG Mode Defaults to True
- Issue: `DEBUG: bool = True` in `Settings` and `docker-compose.yml` passes `DEBUG: "true"` to the backend. FastAPI exposes internal stack traces and SQLAlchemy logs all SQL queries when `echo=settings.DEBUG`.
- Files: `backend/app/core/config.py:19`, `backend/app/core/database.py:8`, `docker-compose.yml:41`
- Impact: Full stack traces and raw SQL exposed in HTTP responses and logs.
- Fix: Default to `False`; override to `True` only in development `.env`.

### 4. Live Pricing Endpoints Require No Authentication
- Issue: `GET /api/v1/live-prices/{mpn}`, `POST /api/v1/live-prices/bom`, and all `/market/*` endpoints have no `Depends(get_current_user)` guard.
- Files: `backend/app/api/live_prices.py`, `backend/app/api/market_intelligence.py`
- Impact: External callers can invoke these endpoints and exhaust paid API quotas (Nexar, DigiKey, OEMsecrets) without authentication.
- Fix: Add `current_user: User = Depends(get_current_user)` to all live-pricing and market endpoints.

### 5. Demo Login Creates/Resets Account with Duplicate DB Commits
- Issue: In `auth.py`, the else branch for an existing demo user calls `db.add(user)` after `db.commit()` — adding an already-persistent object a second time. This causes a silent duplicate-add and an extra unnecessary commit.
- Files: `backend/app/api/auth.py:84-93`
- Impact: Intermittent integrity errors or redundant DB round-trips on every demo login.
- Fix: Remove the redundant `db.add(user)` after the `db.commit()` in the else branch.

---

## Technical Debt

### 1. Orphaned Pre-Pivot Code: `prophet_forecaster.py` and `forecast_tasks.py`
- Issue: Both files import `from app.models.material import PriceHistory, PriceForecast, Material` — a model that was deleted during the data pivot. The `ProphetForecaster` class and `train_all_forecasts` Celery task are completely broken at import time if invoked.
- Files: `backend/app/ml/prophet_forecaster.py`, `backend/app/ml/forecast_tasks.py`
- Impact: Any code path that exercises these modules raises `ModuleNotFoundError`. The Celery worker (`celery_worker` service in `docker-compose.yml`) will fail to start if it imports these tasks.
- Fix: Delete or fully port these files to use `Component` / `DistributorOffer` as the data source.

### 2. Orphaned Scraper: `data_pipeline.py`
- Issue: `backend/app/scrapers/data_pipeline.py` references `from app.models.material import Material, PriceHistory` — same deleted model.
- Files: `backend/app/scrapers/data_pipeline.py`
- Impact: Will crash on import. Dead code that adds confusion.
- Fix: Delete or replace with a pipeline that reads from the current `Component`/`DistributorOffer` schema.

### 3. Missing Foreign Key Constraints on `DistributorOffer` and `CartItem`
- Issue: `component_id` and `distributor_id` columns on `DistributorOffer` and `CartItem` are indexed integers without `ForeignKey(...)` declarations. SQLAlchemy will not enforce referential integrity at the database level.
- Files: `backend/app/models/component.py:27-28`, `backend/app/models/order.py:11-12`
- Impact: Orphaned offers and cart items accumulate when components or distributors are deleted. Solver receives offers referencing non-existent distributors.
- Fix: Add `ForeignKey("components.id", ondelete="CASCADE")` and `ForeignKey("distributors.id", ondelete="CASCADE")` and generate a new Alembic migration.

### 4. Missing Unique Constraint on `DistributorOffer(component_id, distributor_id)`
- Issue: No unique constraint prevents duplicate offers for the same (component, distributor) pair.
- Files: `backend/app/models/component.py`
- Impact: Re-seeding the database creates duplicate offer rows; the solver sees inflated offer counts and `GET /components/{id}/offers` returns duplicate entries.
- Fix: Add `UniqueConstraint("component_id", "distributor_id")` and a migration.

### 5. `ml_lead_time_days` Uses Hardcoded Default Category
- Issue: In `solve.py`, the call to `ml_lead_time_days(...)` passes `component_category="Microcontrollers"` as a hardcoded default regardless of the actual dominant BOM category.
- Files: `backend/app/optimization/solve.py:290`
- Impact: Lead time ML prediction is always biased toward MCU baseline (14 weeks) for every BOM, even if the cart contains only passives (3-week baseline).
- Fix: Derive the actual dominant category from `bom` lines before calling `ml_lead_time_days`.

### 6. `_monte_carlo_eta` Uses Unseeded `random` Module
- Issue: Monte Carlo simulation in `solve.py` uses `random.gauss` and `random.choices` without seeding, making results non-reproducible across runs for the same BOM.
- Files: `backend/app/optimization/solve.py:76-88`
- Impact: ETA confidence intervals vary between identical optimizer runs, undermining trust in the P10/P50/P90 outputs.
- Fix: Accept an optional `seed` parameter or use `numpy.random.default_rng` for reproducible samples.

### 7. Transport Constants Duplicated Between `costs.py` and `sourcing.py`
- Issue: LTL constants (`LTL_BASE = 75.0`, `LTL_RATE = 0.43`, `KM_PER_MILE = 1.60934`, etc.) are copy-pasted verbatim into `sourcing.py` to avoid a circular import.
- Files: `backend/app/optimization/costs.py`, `backend/app/optimization/sourcing.py:253-258`
- Impact: If freight constants are updated in `costs.py`, `sourcing.py` silently diverges. The MILP objective uses different cost coefficients than the route display.
- Fix: Move constants to a standalone `backend/app/optimization/constants.py` module imported by both files.

### 8. `print()` Used for Error Logging Throughout API Clients
- Issue: All six API client files use `print(...)` instead of `logging.getLogger()` for error reporting.
- Files: `backend/app/core/clients/nexar_client.py`, `backend/app/core/clients/digikey_client.py`, `backend/app/core/clients/oemsecrets_client.py`, `backend/app/core/clients/trustedparts_client.py`, `backend/app/core/clients/supplymaven_client.py`, `backend/app/core/clients/easypost_client.py`, `backend/app/core/security.py:52`, `backend/app/api/live_prices.py`
- Impact: Errors are invisible when running under a proper logging framework (e.g., uvicorn's structured logging). Token decode errors could silently fail.
- Fix: Replace `print(...)` with `logger = logging.getLogger(__name__)` and `logger.warning(...)`.

---

## Security Concerns

### 1. JWT Stored in Non-HttpOnly Cookie
- Issue: The frontend stores the JWT access token in a browser cookie without the `httpOnly` flag using `js-cookie`.
- Files: `frontend/src/store/authStore.ts:33`, `frontend/src/store/authStore.ts:42`
- Impact: The token is readable by JavaScript, making it vulnerable to XSS-based token theft.
- Fix: Set `httpOnly: true` on the cookie, which requires the backend to set it as a `Set-Cookie` response header rather than the frontend writing it via JS.

### 2. No Password Complexity Enforcement
- Issue: `UserRegister` schema accepts `password: str` with no minimum length, complexity, or validation.
- Files: `backend/app/api/schemas.py:9`
- Impact: Users can register with empty or single-character passwords.
- Fix: Add `@validator("password")` or use Pydantic `Annotated[str, Field(min_length=8)]`.

### 3. No Rate Limiting on Auth Endpoints
- Issue: `/auth/login`, `/auth/register`, and `/auth/demo` have no rate limiting or brute-force protection.
- Files: `backend/app/api/auth.py`
- Impact: Unrestricted login attempts enable credential brute-forcing.
- Fix: Add `slowapi` or equivalent middleware; limit auth endpoints to ~10 requests/minute per IP.

### 4. Factory Location Validation Only in Registration
- Issue: The US bounds check (`24 <= lat <= 49 and -125 <= lng <= -66`) exists only in the register endpoint. No equivalent check exists in any profile update path.
- Files: `backend/app/api/auth.py:38`
- Impact: Low severity for current scope, but inconsistent validation across auth flows.

### 5. `/live-prices/{mpn}/sync` Allows Unauthenticated DB Writes
- Issue: The `/live-prices/{mpn}/sync` endpoint writes to `DistributorOffer` records with no authentication requirement.
- Files: `backend/app/api/live_prices.py:251-323`
- Impact: Unauthenticated callers can corrupt pricing data in the database, affecting all users' optimization results.
- Fix: Add `Depends(get_current_user)` and consider restricting to admin users only.

---

## Incomplete Features

### 1. Digital Twin ETA Fields Not Populated by Backend
- Issue: `DigitalTwinPage.tsx` displays `result.eta_p50` and `result.eta_p90`, but the `/optimize/scenario` endpoint response object never includes these fields — only `base_total_cost`, `scenario_total_cost`, `cost_delta_pct`, and `item_breakdown` are returned.
- Files: `backend/app/api/optimize.py:207-222`, `frontend/src/pages/DigitalTwinPage.tsx:311-318`
- Impact: ETA panels in the Digital Twin page always display `undefined d` — a silent UI bug visible to any user who runs a scenario.
- Fix: Add Monte Carlo ETA simulation to the scenario endpoint response.

### 2. Prophet Forecaster Fully Broken Post-Pivot
- Issue: `ProphetForecaster` was built for the old materials-based data model and references `app.models.material` which no longer exists. There is no equivalent price forecasting for the current electronic components dataset.
- Files: `backend/app/ml/prophet_forecaster.py`, `backend/app/ml/forecast_tasks.py`
- Impact: Price forecasting feature is completely non-functional. The Celery worker may crash on startup depending on import behavior.
- Fix: Either delete this feature or rewrite for `Component`/`DistributorOffer`.

### 3. Celery Worker Configured but Not Wired to Any Active Task
- Issue: `docker-compose.yml` defines a `celery_worker` service, and `backend/app/core/celery_app.py` exists, but the only registered tasks (`train_all_forecasts`, `train_forecast_for_material`) reference the deleted material model. There are no active scheduled tasks.
- Files: `docker-compose.yml`, `backend/app/ml/forecast_tasks.py`
- Impact: The Celery worker service starts (or fails to start) and does nothing useful.
- Fix: Remove the `celery_worker` service from `docker-compose.yml` until replacement tasks are registered, or register the ML model retraining as a scheduled task.

### 4. ML Model Requires Manual Training Before Server Start
- Issue: Running the server without first executing `python -m seeds.train_ml_models` leaves `current_stress_prob = 0.0` and no lead time models. The optimizer silently falls back to deterministic calculations with no user warning.
- Files: `backend/app/main.py:16-44`, `backend/app/ml/__init__.py`
- Impact: The ML lead time and stress surcharge features are inactive by default with no visibility into this state.
- Fix: Add a health/status endpoint that reports ML model presence; log a prominent startup warning when models are absent.

### 5. `GET /live-prices/{mpn}/sync` Not Exposed in Frontend
- Issue: The sync endpoint exists in the backend but is not called anywhere in the frontend — there is no UI to refresh live pricing for a component.
- Files: `backend/app/api/live_prices.py:251`, `frontend/src/services/api.ts`
- Impact: The HuggingFace static dataset remains unchanged regardless of live API keys being configured. The live-pricing infrastructure is built but never used to update the DB.

---

## Performance Risks

### 1. N+1 Queries in `GET /cart`
- Issue: `get_cart()` fetches all cart items, then issues one separate `db.query(Component)` and one `db.query(Distributor)` per item in a Python loop.
- Files: `backend/app/api/cart.py:49-67`
- Impact: A cart with N items triggers 2N+1 database queries. For a 15-item BOM this is 31 queries per page load.
- Fix: Use a single join query or fetch all component/distributor IDs in batch before the loop.

### 2. N+1 Queries in `GET /components` (List Endpoint)
- Issue: `list_components()` fetches up to 1,000 components, then issues one `db.query(DistributorOffer)` per component to compute price range and offer count.
- Files: `backend/app/api/components.py:86-107`
- Impact: A full component list triggers up to 1,001 queries. The `limit: int = 1000` default makes this worst-case on every Scheduler page load.
- Fix: Replace with a single query using SQLAlchemy `func.min`, `func.max`, `func.count` aggregated via a `JOIN` on `DistributorOffer`, or use a subquery.

### 3. Scenario Endpoint Issues Per-Item DB Queries in a Loop
- Issue: `run_scenario()` loops over cart items and queries `Distributor` and `Component` individually per item.
- Files: `backend/app/api/optimize.py:191-204`
- Impact: Same N+1 pattern as the cart endpoint for every Digital Twin scenario run.
- Fix: Pre-fetch all referenced components and distributors by ID set before the loop.

### 4. VRP Optimizer Loads All Offers for All Components Into Memory
- Issue: `optimize_route()` fetches every `DistributorOffer` for all components in the cart in one query with no filtering. With 8,731 total offers and a 15-component BOM potentially matching hundreds of offers per component, this transfers a large object graph into Python memory.
- Files: `backend/app/api/optimize.py:72-74`
- Impact: Memory footprint grows with dataset size. Not a problem at 8,731 offers but could degrade with a larger dataset.
- Fix: Filter by relevant `distributor_id` set or add a `stock > 0` pre-filter before loading.

### 5. `MapPage.tsx` Has No Lazy Loading or Virtualization
- Issue: `MapPage.tsx` (753 lines) renders all distributors and facility nodes in a single Deck.gl layer call. With potentially thousands of map points, interaction performance depends entirely on Deck.gl's internal rendering.
- Files: `frontend/src/pages/MapPage.tsx`
- Impact: Low risk at current data scale (92 distributors), but any addition of facility nodes (originally 33,884 US power plants) would cause rendering bottlenecks.
- Fix: Add viewport-based filtering or cluster layer for large datasets before enabling facility overlays.

---

## Recommendations

Priority order for addressing concerns:

1. **[Critical]** Fix hardcoded `SECRET_KEY` default — environment validation on startup.
2. **[Critical]** Add auth guards to live-pricing and market intelligence endpoints.
3. **[Critical]** Fix the Digital Twin ETA response gap — `eta_p50`/`eta_p90` are displayed but never sent.
4. **[Critical]** Delete or fix `prophet_forecaster.py` and `data_pipeline.py` — they import a deleted model and will crash if invoked.
5. **[Security]** Restrict `allow_origins` to actual frontend origin; remove wildcard CORS.
6. **[Security]** Add auth to `/live-prices/{mpn}/sync` (unauthenticated DB write endpoint).
7. **[Performance]** Fix N+1 in `GET /cart` and `GET /components` — these are the two most-hit endpoints.
8. **[Debt]** Add FK constraints on `DistributorOffer.component_id` and `DistributorOffer.distributor_id`.
9. **[Debt]** Add unique constraint on `(component_id, distributor_id)` in `DistributorOffer` to prevent duplicate seeding.
10. **[Debt]** Move duplicated freight constants to a shared `constants.py` module.
11. **[Debt]** Replace all `print()` error logging in API clients with `logging.getLogger()`.
12. **[Debt]** Fix hardcoded `component_category="Microcontrollers"` in the ML lead-time call in `solve.py`.
13. **[Polish]** Set `DEBUG: bool = False` as the production default; require explicit override.
14. **[Polish]** Add password minimum length validation in `UserRegister` schema.
