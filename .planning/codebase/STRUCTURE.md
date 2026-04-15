# Codebase Structure
_Last updated: 2026-04-15_

## Summary

The project is a monorepo with `backend/` (Python FastAPI) and `frontend/` (React/TypeScript Vite) as independent applications. The backend is organized into `app/` (runtime code) and `seeds/` (data pipeline + ML training scripts). The frontend follows a flat pages-and-stores pattern with no nested feature folders.

---

## Directory Layout

```
project-root/
├── backend/
│   ├── app/
│   │   ├── api/            # HTTP route handlers (thin controllers)
│   │   ├── core/           # Config, DB, security, Celery, API clients
│   │   ├── ml/             # ML state, regime model, lead time model
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── optimization/   # Domain logic: sourcing MILP, TSP, cross-dock, costs
│   │   ├── scrapers/       # (legacy, unused)
│   │   └── main.py         # FastAPI app factory + lifespan
│   ├── data/
│   │   └── ml_models/      # *.joblib model files (gitignored, regenerated)
│   ├── migrations/         # Alembic migration scripts
│   ├── seeds/              # DB seeding + ML training scripts
│   ├── tests/              # pytest test suite
│   ├── supply_chain.db     # SQLite dev database (gitignored in prod)
│   ├── requirements_minimal.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── NavBar.tsx
│   │   │   └── map/        # Map subcomponents
│   │   ├── hooks/          # (empty — no custom hooks implemented)
│   │   ├── pages/          # Route-level page components
│   │   ├── services/
│   │   │   └── api.ts      # Centralized axios API client
│   │   ├── store/          # Zustand stores
│   │   ├── App.tsx         # Router setup + ProtectedLayout
│   │   └── main.tsx        # React DOM entry point
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── package.json
├── docker-compose.yml
├── CLAUDE.md
└── .planning/
    └── codebase/           # GSD analysis documents
```

---

## Backend Directory Purposes

**`backend/app/api/`**
- Purpose: FastAPI routers. One file per resource group.
- Contains: Route handler functions, inline Pydantic request/response models, `Depends()` wiring.
- Key files:
  - `__init__.py` — assembles all routers into `api_router`
  - `auth.py` — register, login, demo, me; exports `get_current_user` dependency
  - `cart.py` — BOM CRUD with MOQ/stock validation
  - `components.py` — component listing, categories, manufacturers, stats, offers
  - `distributors.py` — distributor listing and detail
  - `optimize.py` — VRP endpoint, cross-dock hubs endpoint, digital twin scenario endpoint
  - `ml.py` — ML stress, model comparison, lead time prediction endpoints
  - `live_prices.py` — live price fetching (optional API integrations)
  - `market_intelligence.py` — market data endpoints

**`backend/app/core/`**
- Purpose: Infrastructure plumbing. No business logic.
- Key files:
  - `config.py` — `Settings(BaseSettings)` with all env vars; imported as `settings` singleton
  - `database.py` — SQLAlchemy engine, `SessionLocal`, `get_db()` dependency
  - `security.py` — bcrypt hashing, JWT encode/decode
  - `celery_app.py` — Celery app instance for async workers
  - `clients/` — Optional external API wrappers (Nexar, DigiKey, EasyPost, OEMsecrets, SupplyMaven, TrustedParts)

**`backend/app/ml/`**
- Purpose: ML model definitions, training helpers, and in-process state.
- Key files:
  - `__init__.py` — `MLState` dataclass, `get_ml_state()` / `set_ml_state()` global accessors
  - `regime_model.py` — logistic regression on FRED time series
  - `lead_time_model.py` — `build_feature_row()`, `predict_lead_time()`, 4 sklearn models
  - `lead_time_labels.py` — category → baseline lead time lookup (`get_base_days()`)
  - `fred_client.py` — FRED API fetching
  - `model_store.py` — `.joblib` file read/write helpers
  - `prophet_forecaster.py` — (supplementary; not wired into main pipeline)
  - `forecast_tasks.py` — Celery task definitions for periodic retraining

**`backend/app/models/`**
- Purpose: SQLAlchemy ORM table definitions.
- Key files:
  - `user.py` — `User` (email, password_hash, factory_name, lat/lng)
  - `component.py` — `Component` + `DistributorOffer`
  - `distributor.py` — `Distributor` (name, lat/lng, city, state, country, is_domestic)
  - `order.py` — `CartItem` + `Order`
  - `cross_dock_hub.py` — `CrossDockHub`
  - `__init__.py` — re-exports all models (imported in `main.py` to trigger `create_all`)

**`backend/app/optimization/`**
- Purpose: All optimization domain logic. No FastAPI dependencies.
- Key files:
  - `sourcing.py` — `BomLine`, `Offer`, `SourcingResult` dataclasses + `solve_sourcing()` CP-SAT MILP
  - `routing.py` — `GeoPoint`, `RoutingNode` + `solve_pickup_tsp()` OR-Tools TSP
  - `cross_dock.py` — `evaluate_cross_dock()` / `evaluate_direct()` consolidation analysis
  - `costs.py` — `haversine_km()`, `transport_cost_usd()`, `co2_kg()`, `holding_cost_usd()`, `ml_lead_time_days()`
  - `strategies.py` — `StrategyWeights` frozen dataclass, `STRATEGIES` list of 4, `normalize_objectives()`
  - `schemas.py` — Pydantic response models: `MultiRouteResponse`, `RouteAlternative`, `RouteStop`, `CostBreakdown`, `StrategyMath`, `CrossDockInfo`, `OutlierDropLog`
  - `solve.py` — `optimize_bom()` orchestrator that wires all stages together
  - `freight_hubs.py` — `FREIGHT_HUBS` list of 10 real US freight hub locations

**`backend/seeds/`**
- Purpose: One-time and scheduled data pipeline scripts. Not imported by the app at runtime.
- Key files:
  - `seed_db.py` — main data load: HuggingFace → SQLite (components, offers, distributors)
  - `train_ml_models.py` — FRED fetch + model training + `.joblib` save
  - `seed_cross_dock_hubs.py` — populates `cross_dock_hubs` table
  - `seed_demo_cart.py` — seeds a demo cart for the demo user
  - `seed_live.py` — live price refresh
  - `cleanup_stale.py` — removes stale records

**`backend/tests/`**
- Purpose: pytest test suite for the optimization domain.
- Key files: `test_sourcing.py`, `test_routing.py`, `test_costs.py`, `test_cross_dock.py`, `test_strategies.py`, `test_lead_time_model.py`, `test_regime_model.py`, `test_fred_client.py`
- Config: `conftest.py`

---

## Frontend Directory Purposes

**`frontend/src/pages/`**
- One file per application screen. Pages are route-level components.
- Key files:
  - `Login.tsx` — email/password + demo login button
  - `Register.tsx` — factory name, email, password, US lat/lng
  - `Dashboard.tsx` — stats overview, factory location display
  - `MapPage.tsx` — Mapbox GL + Deck.gl map showing distributors and facilities (thousands of dots)
  - `SchedulerPage.tsx` — component browser with filtering + competitive price table + add-to-cart
  - `CartPage.tsx` — BOM review, item removal, proceed to checkout
  - `CheckoutPage.tsx` — VRP results display: 4 strategy tabs, route map, sourcing table, cost breakdown, strategy math
  - `DigitalTwinPage.tsx` — scenario simulator (tariff multiplier, distributor failures, demand spike)

**`frontend/src/components/`**
- `NavBar.tsx` — top navigation bar with route links and cart badge
- `map/DistributorSearchBar.tsx` — search input on map
- `map/RouteLegPopup.tsx` — popup for individual route legs
- `map/RouteMetricsBar.tsx` — summary metrics overlay
- `map/RouteTimeline.tsx` — sequential stop timeline

**`frontend/src/store/`**
- Three Zustand stores:
  - `authStore.ts` — auth state, token cookie management, `initializeAuth()`
  - `cartStore.ts` — BOM items, CRUD actions; clears optimize store on any mutation
  - `optimizeStore.ts` — `MultiRouteResult`, `selectedId`, `getSelected()` derived getter

**`frontend/src/services/`**
- `api.ts` — single axios instance; request interceptor adds Bearer token; response interceptor handles 401 redirect; exports `authAPI`, `componentsAPI`, `distributorsAPI`, `cartAPI`, `optimizeAPI` grouped objects.

**`frontend/src/App.tsx`**
- Defines `ProtectedLayout` (redirects unauthenticated users to `/login`) and `BrowserRouter` routes.
- Calls `initializeAuth()` on mount to restore session from cookie.

---

## Key File Locations (Quick Reference)

| What | File |
|---|---|
| FastAPI app factory | `backend/app/main.py` |
| All routers registered | `backend/app/api/__init__.py` |
| VRP endpoint | `backend/app/api/optimize.py` |
| Optimization orchestrator | `backend/app/optimization/solve.py` |
| CP-SAT MILP sourcing | `backend/app/optimization/sourcing.py` |
| TSP routing | `backend/app/optimization/routing.py` |
| Cost/CO2 formulas | `backend/app/optimization/costs.py` |
| Strategy weight profiles | `backend/app/optimization/strategies.py` |
| Optimization Pydantic schemas | `backend/app/optimization/schemas.py` |
| ML state singleton | `backend/app/ml/__init__.py` |
| ML lead time predictor | `backend/app/ml/lead_time_model.py` |
| All ORM models | `backend/app/models/__init__.py` |
| DB engine + session | `backend/app/core/database.py` |
| App settings | `backend/app/core/config.py` |
| DB seed script | `backend/seeds/seed_db.py` |
| ML training script | `backend/seeds/train_ml_models.py` |
| Frontend API client | `frontend/src/services/api.ts` |
| React router + layout | `frontend/src/App.tsx` |
| Auth Zustand store | `frontend/src/store/authStore.ts` |
| Cart Zustand store | `frontend/src/store/cartStore.ts` |
| Optimize Zustand store | `frontend/src/store/optimizeStore.ts` |
| Checkout / VRP UI | `frontend/src/pages/CheckoutPage.tsx` |
| Map visualization | `frontend/src/pages/MapPage.tsx` |

---

## Naming Conventions

**Backend files:**
- Snake_case modules: `seed_db.py`, `lead_time_model.py`, `cross_dock.py`
- One module per resource in `api/`; one module per concern in `optimization/`
- ORM models: PascalCase class names matching table name in snake_case: `DistributorOffer` → `distributor_offers`

**Frontend files:**
- PascalCase for page and component files: `CheckoutPage.tsx`, `NavBar.tsx`
- camelCase for store and service files: `authStore.ts`, `api.ts`
- No barrel files (`index.ts`) in `pages/` or `store/` — import by full path

---

## Where to Add New Code

**New API endpoint:**
- Add route handler to the relevant file in `backend/app/api/` (or create a new file)
- Register new router in `backend/app/api/__init__.py`
- Add corresponding API function to `frontend/src/services/api.ts`

**New ORM model:**
- Create `backend/app/models/{name}.py` with `Base`-derived class
- Register in `backend/app/models/__init__.py`
- Run `alembic revision --autogenerate` from `backend/`

**New optimization logic:**
- Add to appropriate module in `backend/app/optimization/` (keep pure Python, no FastAPI imports)
- Wire into `solve.py` orchestrator if it affects the VRP pipeline
- Add new Pydantic output fields to `backend/app/optimization/schemas.py`

**New frontend page:**
- Create `frontend/src/pages/{Name}Page.tsx`
- Add `<Route>` in `frontend/src/App.tsx` inside `ProtectedLayout`
- Add nav link in `frontend/src/components/NavBar.tsx`

**New Zustand store:**
- Create `frontend/src/store/{name}Store.ts`
- Import in pages that need it via `use{Name}Store`

**New seed script:**
- Create `backend/seeds/{purpose}.py`
- Can be run standalone: `cd backend && python -m seeds.{purpose}`

---

## Special Directories

**`backend/data/ml_models/`**
- Contains: `regime.joblib`, `lead_time.joblib`, `feature_cols.joblib`, `metrics.joblib`
- Generated by: `python -m seeds.train_ml_models`
- Committed: No (gitignored)
- Server behavior: Loaded at startup in `main.py` lifespan handler; server runs without them (ML features disabled)

**`backend/migrations/`**
- Contains: Alembic migration scripts
- Config: `backend/alembic.ini`
- Note: Dev workflow uses `Base.metadata.create_all(bind=engine)` in `main.py` (no migration needed for SQLite dev)

**`.planning/codebase/`**
- Contains: GSD analysis documents (STACK.md, ARCHITECTURE.md, STRUCTURE.md, etc.)
- Generated by: `/gsd-map-codebase` agent
- Committed: Yes

---

*Structure analysis: 2026-04-15*
