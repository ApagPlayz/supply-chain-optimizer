# Architecture
_Last updated: 2026-04-15_

## Summary

The system is a full-stack supply chain route optimization platform. The backend is a Python FastAPI service using SQLAlchemy with SQLite (dev) / PostgreSQL (prod). The frontend is a React/TypeScript SPA. The core value is a two-stage optimization pipeline: a CP-SAT integer program (Stage 1) selects the cheapest valid supplier assignment per BOM line, then an OR-Tools TSP solver (Stage 2) sequences the resulting distributor pickup stops into a minimum-distance route.

---

## Overall Pattern

**Backend:** Layered FastAPI — thin HTTP routers delegate to a pure-Python optimization domain (`app/optimization/`). No ORM relationships used (foreign keys are plain integers, joins done explicitly in API handlers). Pydantic v2 schemas for all request/response shapes.

**Frontend:** Single-page app with Zustand stores for auth, cart, and optimization result state. All API calls are centralized in `frontend/src/services/api.ts`. Pages are route-level components; no shared component library beyond NavBar and a handful of map subcomponents.

**Communication:** REST JSON. JWT Bearer tokens in cookies (`access_token`). Vite dev proxy routes `/api` → `http://localhost:8000`.

---

## Backend Layers

**HTTP Layer — `backend/app/api/`**
- Purpose: Parse requests, enforce auth, call domain functions, serialize responses.
- Files: `auth.py`, `cart.py`, `components.py`, `distributors.py`, `optimize.py`, `ml.py`, `live_prices.py`, `market_intelligence.py`
- Registered in `backend/app/api/__init__.py` as a single `api_router` mounted at `/api/v1`.
- Auth dependency `get_current_user` (defined in `auth.py`) is injected via `Depends` into any protected endpoint.

**Domain / Optimization — `backend/app/optimization/`**
- Purpose: All optimization logic. Zero FastAPI imports; pure Python dataclasses + OR-Tools.
- Key files:
  - `sourcing.py` — Stage 1: CP-SAT MILP sourcing solver (`solve_sourcing`)
  - `routing.py` — Stage 2: OR-Tools TSP pickup solver (`solve_pickup_tsp`)
  - `cross_dock.py` — Cross-dock consolidation analysis (`evaluate_cross_dock`)
  - `costs.py` — Freight cost, CO2, holding cost, and ML-delegating lead time functions
  - `strategies.py` — Four `StrategyWeights` dataclasses + objective normalization
  - `schemas.py` — Pydantic response models (`MultiRouteResponse`, `RouteAlternative`, etc.)
  - `solve.py` — Orchestrator: runs all 4 strategies end-to-end, produces `MultiRouteResponse`

**ML Layer — `backend/app/ml/`**
- Purpose: Macro stress regime detection + lead time prediction. Loaded at startup; zero training at request time.
- Key files: `__init__.py` (global `MLState` singleton), `regime_model.py`, `lead_time_model.py`, `fred_client.py`, `model_store.py`
- Models stored as `backend/data/ml_models/*.joblib` (gitignored). Trained via `backend/seeds/train_ml_models.py`.
- Access pattern: `get_ml_state()` returns `MLState | None`. `costs.py` calls this inside `ml_lead_time_days()`. `sourcing.py` calls it to compute stock-out risk surcharges inside the MILP objective.

**Data Models — `backend/app/models/`**
- Pure SQLAlchemy ORM classes. No relationships declared (all joins are manual in API handlers).
- Key models: `User`, `Component`, `DistributorOffer`, `Distributor`, `CartItem`, `Order`, `CrossDockHub`
- All registered in `backend/app/models/__init__.py` and imported in `main.py` before `Base.metadata.create_all`.

**Core Infrastructure — `backend/app/core/`**
- `config.py` — `pydantic_settings.BaseSettings` reading from `.env`; exposes `settings` singleton
- `database.py` — SQLAlchemy engine + `SessionLocal` + `get_db()` FastAPI dependency
- `security.py` — `bcrypt` password hashing, `python-jose` JWT encode/decode
- `celery_app.py` — Celery worker config (used in Docker prod; not active in local dev)
- `clients/` — Optional API client wrappers: `nexar_client.py`, `digikey_client.py`, `easypost_client.py`, `oemsecrets_client.py`, `supplymaven_client.py`, `trustedparts_client.py`

**Seeds — `backend/seeds/`**
- `seed_db.py` — Pulls `mdnh/electronic-components-supply-chain` from HuggingFace, maps 92 distributors to real US warehouse coordinates, populates SQLite.
- `train_ml_models.py` — Fetches FRED time series, trains regime + lead time models, saves `.joblib` files.
- `seed_cross_dock_hubs.py`, `seed_demo_cart.py`, `seed_live.py` — Supporting seed scripts.

---

## Optimization Pipeline (Request Path for `POST /api/v1/optimize/vrp`)

1. **`api/optimize.py` → `optimize_route()`**
   - Loads user's `CartItem` rows from DB.
   - Builds `BomLine` list (component + quantity per cart item).
   - Fetches all `DistributorOffer` rows for those components.
   - Constructs `Offer` objects with precomputed haversine distances from the user's factory lat/lng (`depot`).
   - Calls `optimize_bom(bom, offers, distributors_meta, depot, us_only)`.

2. **`optimization/solve.py` → `optimize_bom()`**
   - For each of the 4 strategies, calls `solve_sourcing()` (cached by `us_only_sourcing + transport_penalty_scale` key to avoid redundant MILP solves when strategies share the same supplier pool).
   - For each strategy, calls `solve_pickup_tsp()` over the selected distributors.
   - Calls `evaluate_cross_dock()` to check whether routing through a freight hub beats direct pickup by ≥5%.
   - Assembles `RouteAlternative` with stops, cost breakdown, strategy math, cross-dock info, and Monte Carlo ETA percentiles.
   - Returns `MultiRouteResponse` with all 4 alternatives ranked.

3. **`optimization/sourcing.py` → `solve_sourcing()`**
   - Filters outlier-priced offers (price > 5× component median dropped).
   - Optionally filters to domestic-only offers.
   - Builds CP-SAT model: binary `x[cid,did]` (select offer), integer `q[cid,did]` (quantity), binary `y[did]` (visit distributor).
   - Constraints: demand coverage, stock cap, MOQ floor, distributor linking.
   - Objective: component cost + transport penalty (scaled by strategy) + consolidation bonus + ML stock-out risk surcharge.
   - Solver timeout: 5 seconds.

4. **`optimization/routing.py` → `solve_pickup_tsp()`**
   - OR-Tools `pywrapcp.RoutingModel` with haversine distance matrix.
   - `PATH_CHEAPEST_ARC` initial solution + `GUIDED_LOCAL_SEARCH` metaheuristic.
   - 3-second time limit; falls back to nearest-neighbor greedy on failure.

5. **`optimization/cross_dock.py` → `evaluate_cross_dock()`**
   - Enumerates 10 candidate US freight hubs (`optimization/freight_hubs.py`).
   - For each hub: computes N LTL legs (distributor→hub) + 1 consolidated leg (hub→depot).
   - Picks best hub; only enables if it beats direct tour by ≥5%.

6. **`optimization/costs.py`**
   - `transport_cost_usd()` — LTL vs TL rate selection at 10,000 lbs threshold (ATRI 2023).
   - `co2_kg()` — EPA SmartWay 2023 factor (161.8 g CO2e/ton-mile).
   - `holding_cost_usd()` — Gartner 2022 electronics holding rate (25% annual).
   - `ml_lead_time_days()` — delegates to ML lead time model if loaded; falls back to `leg_lead_time_days()`.

---

## Four Optimization Strategies

Defined in `backend/app/optimization/strategies.py` as frozen `StrategyWeights` dataclasses:

| ID | Label | `us_only_sourcing` | `transport_penalty_scale` | `consolidation_bonus_usd` |
|---|---|---|---|---|
| `cheapest` | Best Unit Price | False | 0.0 (pure unit cost) | 1.0 |
| `fastest` | Fastest Delivery | True (domestic only) | 0.0 | 1.0 |
| `greenest` | Lowest Carbon | False | 3.0 (strong proximity) | 500.0 |
| `balanced` | Lowest Total Cost | False | 1.0 (full landed cost) | 50.0 |

Final selection scores are weighted-sum scalarization over min-max normalized `(cost, time, carbon)` objectives.

---

## Data Flow — User Journey

```
Login / Register
  → POST /auth/login or /auth/register
  → JWT stored in js-cookie (7-day expiry)
  → initializeAuth() on app load hydrates user profile via GET /auth/me

Browse Components (SchedulerPage)
  → GET /components?category=...&search=...
  → GET /components/{id}/offers (ranked by price)
  → POST /cart (component_id, distributor_id, quantity, unit_price)
  → CartItem persisted with auto-looked-up price from DistributorOffer

Checkout (CheckoutPage)
  → POST /optimize/vrp
  → optimize_bom() runs 4 strategies → MultiRouteResponse
  → Order row created for "balanced" strategy
  → optimizeStore.setMultiResult() hydrates frontend state
  → Route arcs rendered via Deck.gl ArcLayer on Mapbox base map

Digital Twin (DigitalTwinPage)
  → POST /optimize/scenario
  → Applies tariff multiplier / distributor failures / demand spike
  → Returns simplified cost delta (no VRP re-solve)
```

---

## Authentication Flow

- JWT issued by `security.create_access_token({"sub": str(user.id)})`, default 30-minute expiry.
- Token stored in `js-cookie` (`access_token`, 7-day client cookie).
- `api.ts` request interceptor attaches `Authorization: Bearer <token>` header.
- `api.ts` response interceptor catches 401 → removes cookie → redirects to `/login`.
- Backend: `get_current_user` FastAPI dependency decodes token → loads `User` row.

---

## Error Handling

- **API layer:** Raises `HTTPException` with appropriate status codes. No global exception handler.
- **Optimizer:** `solve_sourcing()` raises `ValueError` (infeasible BOM) or `RuntimeError` (solver failure); caught in `optimize.py` and converted to 400/500.
- **ML:** All ML inference is wrapped in `try/except Exception: pass` with deterministic fallback. Server continues without ML if models are absent.
- **Frontend:** Per-store `error` state; no global error boundary. 401 responses auto-redirect to login.

---

## State Management (Frontend)

Three Zustand stores in `frontend/src/store/`:

- `authStore.ts` — `user`, `token`, `isAuthenticated`. Persists token in cookie. `initializeAuth()` called in `App.tsx` `useEffect` on mount.
- `cartStore.ts` — `items[]`. Calls `optimizeStore.clearResult()` on any mutation to invalidate stale optimization results.
- `optimizeStore.ts` — `multiResult`, `selectedId`. `getSelected()` derived getter returns the active `RouteAlternative`.

---

## API Design Conventions

All endpoints under `/api/v1`. Router prefixes defined per module:

| Module | Prefix | Auth required |
|---|---|---|
| `auth.py` | `/auth` | No (except `/auth/me`) |
| `components.py` | `/components` | No |
| `distributors.py` | `/distributors` | No |
| `cart.py` | `/cart` | Yes |
| `optimize.py` | `/optimize` | Yes (except `/optimize/hubs`) |
| `ml.py` | `/ml` | No |
| `live_prices.py` | `/live-prices` | No |
| `market_intelligence.py` | `/market-intelligence` | No |

Pydantic response models are defined inline in each `api/` file (not in a shared `schemas.py`), except for optimization responses which live in `optimization/schemas.py`.

---

## Production Topology (Docker)

Defined in `docker-compose.yml`:
- **PostgreSQL 16** — primary DB (SQLite used in local dev)
- **Redis 7** — Celery broker
- **backend** — uvicorn server
- **celery_worker** — async task worker (data pulls, model training)

---

*Architecture analysis: 2026-04-15*
