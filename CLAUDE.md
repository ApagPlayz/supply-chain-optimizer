# CLAUDE.md — Supply Chain Intelligence Platform

## Project Status: Phase 5-6 Complete ✅

**Last Updated:** April 7, 2026 — All Phase 5 (Cart/VRP) and Phase 6 (Digital Twin/ESG) features are implemented, TypeScript compilation fixed, and backend is operational.

## Project Goal
Build a portfolio-grade supply chain optimization web app targeting roles at McKinsey, BCG, Amazon, Apple Ops, and consulting firms. Full-stack: FastAPI backend, React TypeScript frontend, OR-Tools route optimization.

## Tech Stack
- **Backend:** Python 3.11 + FastAPI + SQLite/PostgreSQL + Redis (optional) + Celery (optional)
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS v4.2 + Mapbox GL + Deck.gl v9.2
- **Optimization:** Google OR-Tools VRP solver (multi-objective: cost + time + CO2)
- **Data:** Seeded with 25 production hubs, 171 materials, 59 suppliers across US
- **Infra:** SQLite for dev (no DB setup needed), Docker Compose for prod

## Implementation Status

### ✅ Completed Features

**Phase 1 — Foundation** (FastAPI, React, JWT Auth, CORS)
- User registration/login with JWT tokens in httpOnly cookies
- Auth middleware and protected routes
- Database models for users, materials, suppliers, hubs

**Phase 2 — Materials & Hubs** (Inventory & Network)
- 171 materials seeded across 10 categories (semiconductors, batteries, rare earth, chemicals, metals, etc.)
- 25 US production hubs with geographic distribution
- Material price history and forecast endpoints
- Supplier recommendations API

**Phase 3 — Maps & Visualization** (Mapbox + Deck.gl)
- Interactive Mapbox map with hub markers color-coded by risk
- 3D Deck.gl arc layers showing factory-to-hub supply routes
- Dynamic risk-based styling (low/moderate/high/critical)
- Hub detail sidebar with supplier and material info
- Route timeline component with stop-by-stop metrics

**Phase 4 — Scheduler & Cart**
- Material browser with category filtering and search
- Price history charts with forecast overlays
- Supplier ranking by reliability, cost, lead time
- Add-to-cart with quantity selection
- Cart management (add, remove, clear)

**Phase 5 — Route Optimization & Checkout** ✅
- OR-Tools multi-objective VRP solver (4 strategies: cheapest, fastest, greenest, balanced)
- Monte Carlo delivery time simulation (P10/P50/P90 percentiles)
- Carbon footprint calculation (kg CO2e per route)
- Cost breakdown (material + transport)
- Route visualization with numbered stops and leg metrics
- Strategy comparison table with ranked metrics
- Order persistence to database

**Phase 6 — Digital Twin & ESG** ✅
- **DigitalTwinPage:** Scenario testing with 4 presets (Trade War, Port Strike, Supplier Failure, Shortage)
- Tariff and demand spike sliders (1.0–3.0 multiplier)
- Impact analysis: cost delta, ETA disruption, item breakdown
- **ESGDashboard:** Composite sustainability score (0–100)
  - 40% Carbon Efficiency (greenest vs cheapest CO2)
  - 35% Resilience (1 − avg supply risk)
  - 25% Geographic Diversification (unique states / total stops)
  - Pareto frontier visualization (cost vs CO2 scatter)
  - Supply risk by category (bar chart)
  - Material risk matrix (volatility vs supply risk)
  - Carbon KPI cards for each strategy

**Navigation & UI** ✅
- NavBar with links to all pages (Dashboard, Map, Scheduler, Cart, Checkout, Digital Twin, ESG)
- Protected layout with loading spinner
- Proper error handling for FastAPI 422 validation errors
- Loading states and empty state messaging

### 🔧 Recent Fixes (April 7, 2026)

- **TypeScript Errors:** Fixed 15 compilation errors (unused imports, Framer Motion types, MapLibre type issues)
- **Build Success:** Frontend now compiles without warnings
- **Backend Dependencies:** Confirmed core packages work (FastAPI, SQLAlchemy, Pydantic, OR-Tools)
- **Database Seeding:** 25 hubs + 171 materials + 59 suppliers loaded
- **Error Serialization:** Proper handling of FastAPI 422 array-format validation errors

## How to Run (Local Development)

### Quick Start (SQLite, 2 minutes)

```bash
# 1. Install backend dependencies (once)
cd backend
pip install -r requirements_minimal.txt

# 2. Seed the database (once)
python3 -m seeds.seed_db

# 3. Start backend (Terminal 1)
cd backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 4. Start frontend (Terminal 2)
cd frontend
npm install  # if needed
npm run dev

# 5. Open http://localhost:5173
```

### Using Docker (if available)

```bash
docker compose up -d
# Then seed: docker compose exec backend python3 -m seeds.seed_db
```

## Testing Workflow

```
1. Login page → register new user or use demo login
2. Dashboard → see factory location on map (blue pin)
3. Map page → view 25 hubs (colored by type), toggle risk arcs
4. Scheduler → browse materials, select supplier, add to cart
5. Cart → review items, proceed to checkout
6. Checkout (Optimize page) → VRP solver runs, shows 4 routes
   - Cheapest route highlighted in green
   - Compare cost/time/CO2 across strategies
   - Click "View Route on Map" to visualize stops
   - Click "Confirm Order" to save
7. Digital Twin → test scenarios (tariffs, supplier failures)
8. ESG → see sustainability score and Pareto frontier
```

## API Endpoints

All at `http://localhost:8000/api/v1`

### Auth
- `POST /auth/register` → Create user account
- `POST /auth/login` → Get JWT token
- `POST /auth/demo` → Demo login
- `GET /auth/me` → Current user profile

### Materials & Suppliers
- `GET /materials` → List with filters (category, search)
- `GET /materials/:id` → Detail + price history + forecast
- `GET /materials/:id/suppliers` → Top suppliers for material
- `GET /materials/categories` → All categories

### Hubs & Network
- `GET /hubs` → List all 25 production hubs
- `POST /hubs/nearby` → Find hubs within radius

### Cart
- `GET /cart` → User's cart items
- `POST /cart` → Add item (material_id, supplier_id, quantity)
- `DELETE /cart/:item_id` → Remove item
- `DELETE /cart` → Clear all

### Optimization
- `POST /optimize/vrp` → Run route solver, returns 4 strategies
- `POST /optimize/scenario` → What-if analysis (tariff_multiplier, supplier_failures, etc.)

Check interactive docs at `http://localhost:8000/api/v1/docs` (Swagger UI)

## Code Organization

```
backend/app/
  api/          # Route handlers
    ├── auth.py        → JWT, registration, login
    ├── cart.py        → Cart CRUD
    ├── hubs.py        → Hub endpoints
    ├── materials.py   → Material, price, supplier endpoints
    └── optimize.py    → VRP solver, scenario analysis
  
  models/       # SQLAlchemy ORM
    ├── user.py
    ├── material.py
    ├── supplier.py
    ├── hub.py
    ├── order.py       → Order + CartItem tables
    └── __init__.py    → Register all models
  
  core/         # Infrastructure
    ├── config.py      → Settings from .env
    ├── database.py    → SQLAlchemy engine + session
    ├── security.py    → Password hashing, JWT
    └── celery_app.py  → Task queue (optional)
  
  main.py       → FastAPI app, middleware, routes

frontend/src/
  pages/
    ├── Login.tsx           → Auth form
    ├── Dashboard.tsx       → Stats, recent orders
    ├── MapPage.tsx         → Interactive map + 3D arcs
    ├── SchedulerPage.tsx   → Material browser + cart
    ├── CartPage.tsx        → Cart review
    ├── CheckoutPage.tsx    → VRP results + route selection
    ├── DigitalTwinPage.tsx → Scenario simulator
    └── ESGDashboard.tsx    → Sustainability metrics
  
  components/
    ├── NavBar.tsx          → Top navigation
    └── map/
        ├── DeckGLOverlay.tsx        → 3D arc layer wrapper
        ├── MapLegendFilter.tsx      → Hub type + risk filters
        ├── HubDetailSidebar.tsx     → Hub popover
        └── RouteTimeline.tsx        → Route stops list
  
  store/
    ├── authStore.ts        → JWT, user state
    ├── cartStore.ts        → Cart items
    └── optimizeStore.ts    → VRP results
  
  services/
    └── api.ts             → Axios client + endpoint definitions
```

## Key Implementation Details

### 1. Authentication
- JWT tokens stored in httpOnly cookies (httpOnly: true, secure: true, sameSite: 'lax')
- Token refresh handled by interceptors
- 401 redirects to /login automatically

### 2. Multi-Objective VRP
- OR-Tools ConstraintSolver with weighted cost matrix
- 4 strategies: cost (0.8/0.1/0.1), time (0.1/0.8/0.1), carbon (0.1/0.1/0.8), balanced (0.34/0.33/0.33)
- Haversine distance + load-based CO2 estimation
- Fallback to nearest-neighbor heuristic if OR-Tools unavailable

### 3. Error Handling
- FastAPI 422 validation errors returned as array: `[{msg, loc, type, input}]`
- Frontend serializes to user-friendly string: "invalid quantity, invalid supplier_id"
- Also applied to scenario API responses

### 4. Visualization
- Mapbox GL base layer (US-only bounds via northEast/southWest)
- Deck.gl ArcLayer with 3D tilt for supply route arcs
- Risk-based coloring: low (green), moderate (yellow), high (orange), critical (red)
- Recharts for all analytics (scatter, bar, area charts)

### 5. Database
- SQLite in dev (no setup needed)
- Alembic migrations in `backend/migrations/`
- Seed script creates 25 hubs with realistic geo distribution
- 171 materials across 10 categories with synthetic price/supply risk

## Dependencies Summary

### Backend
- **Web:** fastapi, uvicorn, python-jose, passlib, bcrypt
- **Database:** sqlalchemy, alembic
- **Config:** pydantic, pydantic-settings, python-dotenv
- **Optimization:** ortools
- **Utils:** requests, beautifulsoup4, httpx

### Frontend
- **UI Framework:** react, react-router-dom
- **Styling:** tailwind (v4.2), framer-motion
- **State:** zustand
- **Charts:** recharts
- **Maps:** mapbox-gl, react-map-gl, @deck.gl (7 packages), maplibre-gl
- **Icons:** lucide-react
- **HTTP:** axios
- **Build:** vite, typescript (strict mode)

## Next Steps (Future)

- [ ] Add Prophet ML for price forecasting (requires pandas, numpy — optional)
- [ ] Implement Celery background tasks for data pulls
- [ ] Add PostgreSQL + PostGIS for geospatial queries
- [ ] Integrate external APIs (FRED, EIA, Alpha Vantage)
- [ ] Add Monte Carlo simulation to digital twin
- [ ] Export reports (PDF, CSV)
- [ ] Real-time collaboration features
- [ ] Mobile app (React Native)

## Commit History (Recent)

- `fix: resolve TypeScript compilation errors` — Fixed 15 TS errors, build now succeeds
- `feat: phase 1 foundation with FastAPI, React, Docker, and JWT auth` — Initial scaffolding
