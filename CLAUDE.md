# CLAUDE.md — Electronic Components Supply Chain Optimizer

## Project Status: Data Pivot In Progress 🔄

**Last Updated:** April 7, 2026 — Pivoting from synthetic materials to real electronic components data from Nexar/Octopart via Hugging Face. Backend overhaul underway; frontend functionality preserved.

## Project Goal
Build a portfolio-grade supply chain route optimization platform targeting roles at McKinsey, BCG, Amazon, Apple Ops, and consulting firms. Demonstrates multi-objective VRP solving over **real supplier data** — 791 electronic components, 92 real distributors (DigiKey, Mouser, Arrow, Avnet...), 8,731 competitive price offers, and real US warehouse locations.

## Core Value Proposition
Given a Bill of Materials (BOM) — e.g., "I need 15 components for a PCB build" — the optimizer finds the best combination of distributors minimizing **cost + shipping time + supply risk**, considering:
- **Real competitive pricing** — same component priced differently across 92 distributors
- **Real stock levels** — availability constraints affect routing decisions
- **Real distributor warehouse locations** — driving distances matter
- **Risk scores** — geopolitical risk (Chinese origin), single-source risk, stock scarcity
- **Multi-stop route optimization** — OR-Tools VRP across distributor warehouses

## Data Sources (ALL REAL)

### Primary: Nexar/Octopart Electronic Components (via Hugging Face)
- **Dataset:** `mdnh/electronic-components-supply-chain`
- **791 components** across 54 categories (microcontrollers, ADCs, DSPs, op-amps, memory, SoCs, RF, motor drivers...)
- **8,731 supplier offers** with real prices, SKUs, and stock levels
- **92 real distributors:** DigiKey, Mouser, Arrow Electronics, Avnet, Newark, Farnell, TME, Future Electronics, Rochester Electronics, LCSC, etc.
- **Risk data:** per-component risk scores, risk factors (chinese_origin, single_source, etc.)
- **Manufacturer data:** Espressif, Texas Instruments, Analog Devices, Microchip, STMicroelectronics, etc.

### Secondary: Data Commons (Google)
- **33,884 US power plants** (EIA-860) — real lat/lng, capacity, fuel type, NAICS codes
- **10,512 EPA reporting facilities** — real industrial manufacturers with addresses
- Used as delivery destination nodes for route visualization
- API key required: https://apikeys.datacommons.org/

### Distributor Warehouse Locations
- 92 distributors mapped to real US headquarters/warehouse coordinates
- Major distributors: DigiKey (Thief River Falls, MN), Mouser (Mansfield, TX), Arrow (Centennial, CO), Avnet (Phoenix, AZ), Newark (Chicago, IL), etc.

## Tech Stack
- **Backend:** Python 3.11 + FastAPI + SQLite/PostgreSQL
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS v4.2 + Mapbox GL + Deck.gl v9.2
- **Optimization:** Google OR-Tools VRP solver (multi-objective: cost + time + CO2)
- **Data Pipeline:** HuggingFace `datasets` library → SQLite ingestion
- **Infra:** SQLite for dev, Docker Compose for prod

## Architecture

### Data Model
```
Component (was Material)
  ├── mpn (manufacturer part number)
  ├── manufacturer, manufacturer_country
  ├── category (54 types)
  ├── description, datasheets
  ├── risk_score, risk_factors
  └── has many → DistributorOffer

Distributor (was Supplier)
  ├── name (DigiKey, Mouser, etc.)
  ├── latitude, longitude (real warehouse location)
  ├── city, state, country
  ├── is_domestic
  └── has many → DistributorOffer

DistributorOffer (NEW — real competitive pricing)
  ├── component_id → Component
  ├── distributor_id → Distributor
  ├── price (real USD price from Nexar)
  ├── stock (real inventory count)
  ├── sku (real distributor SKU)
  ├── currency
  └── moq (minimum order quantity)
```

### Optimization Problem
**Input:** User's cart (BOM) — list of components + quantities
**Constraints:** Stock availability, MOQ, budget limits
**Objectives:** Minimize weighted combination of:
  1. **Total cost** (component prices × quantities + transport cost)
  2. **Shipping time** (based on real distances between distributor warehouses)
  3. **Supply risk** (component risk scores + geopolitical factors)
  4. **Carbon footprint** (distance-based CO2 estimation)
**Output:** 4 strategies (cheapest, fastest, lowest-risk, balanced) with route visualization

## How to Run (Local Development)

```bash
# 1. Install backend dependencies
cd backend
pip install -r requirements_minimal.txt

# 2. Seed the database (pulls real data from HuggingFace)
python3 -m seeds.seed_db

# 3. Start backend (Terminal 1)
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 4. Start frontend (Terminal 2)
cd frontend
npm install && npm run dev

# 5. Open http://localhost:5173
```

## Testing Workflow
```
1. Login → register or demo login
2. Dashboard → overview stats, factory location
3. Map → view distributor warehouses + facility nodes (thousands of dots)
4. Scheduler → browse 791 components, see competing distributor prices, add to cart
5. Cart → review BOM, proceed to checkout
6. Checkout → VRP solver finds optimal distributor routes across 4 strategies
7. Digital Twin → scenario testing (tariffs, supplier failures, demand spikes)
```

## API Endpoints

All at `http://localhost:8000/api/v1`

### Auth
- `POST /auth/register` → Create user account
- `POST /auth/login` → Get JWT token
- `POST /auth/demo` → Demo login
- `GET /auth/me` → Current user profile

### Components (was Materials)
- `GET /components` → List with filters (category, search, manufacturer)
- `GET /components/:id` → Detail + offers from all distributors
- `GET /components/:id/offers` → Ranked distributor offers (price, stock, risk)
- `GET /components/categories` → All 54 categories

### Distributors (was Suppliers/Hubs)
- `GET /distributors` → All 92 with locations
- `GET /distributors/:id` → Detail + components they carry

### Cart
- `GET /cart` → User's BOM
- `POST /cart` → Add component (component_id, distributor_id, quantity, unit_price)
- `DELETE /cart/:item_id` → Remove
- `DELETE /cart` → Clear all

### Optimization
- `POST /optimize/vrp` → Route solver across distributor warehouses
- `POST /optimize/scenario` → What-if analysis

## Code Organization

```
backend/app/
  api/
    ├── auth.py         → JWT, registration, login
    ├── cart.py          → Cart/BOM CRUD
    ├── components.py    → Component browsing + distributor offers
    ├── distributors.py  → Distributor locations
    └── optimize.py      → VRP solver, scenario analysis

  models/
    ├── user.py
    ├── component.py     → Component + DistributorOffer
    ├── distributor.py   → Distributor with warehouse location
    ├── order.py         → Order + CartItem
    └── __init__.py

  core/
    ├── config.py        → Settings from .env
    ├── database.py      → SQLAlchemy engine + session
    ├── security.py      → Password hashing, JWT
    └── data_fetcher.py  → FRED/Alpha Vantage API client (optional)

  main.py               → FastAPI app, middleware, routes

backend/seeds/
  └── seed_db.py         → Pulls from HuggingFace, maps distributors, seeds DB

frontend/src/
  pages/
    ├── Login.tsx
    ├── Dashboard.tsx
    ├── MapPage.tsx          → Thousands of dots (distributors + facilities)
    ├── SchedulerPage.tsx    → Component browser + competitive pricing
    ├── CartPage.tsx         → BOM review
    ├── CheckoutPage.tsx     → VRP results + route visualization
    └── DigitalTwinPage.tsx  → Scenario simulator

  components/
    ├── NavBar.tsx
    └── map/
        ├── DeckGLOverlay.tsx
        ├── MapLegendFilter.tsx
        ├── HubDetailSidebar.tsx
        └── RouteTimeline.tsx

  store/
    ├── authStore.ts
    ├── cartStore.ts
    └── optimizeStore.ts

  services/
    └── api.ts
```

## Key Implementation Details

### 1. Authentication
- JWT tokens stored in httpOnly cookies
- Token refresh handled by interceptors
- 401 redirects to /login automatically

### 2. Multi-Objective VRP
- OR-Tools ConstraintSolver with weighted cost matrix
- 4 strategies: cost (0.8/0.1/0.1), time (0.1/0.8/0.1), risk (0.1/0.1/0.8), balanced (0.34/0.33/0.33)
- Real haversine distances between distributor warehouses
- Transport cost based on distance + load weight

### 3. Real Data Pipeline
- HuggingFace `datasets` library pulls `mdnh/electronic-components-supply-chain`
- 791 components with nested supplier offers parsed and normalized
- 92 distributors mapped to real US warehouse coordinates
- Risk scores and factors preserved from source data

### 4. Visualization
- Mapbox GL base layer with thousands of location markers
- Deck.gl ScatterplotLayer for distributor/facility density
- ArcLayer for optimized supply routes
- Risk-based coloring per component and distributor
- Recharts for price comparison, risk analysis

## Dependencies

### Backend
- **Web:** fastapi, uvicorn, python-jose, passlib, bcrypt
- **Database:** sqlalchemy, alembic
- **Config:** pydantic, pydantic-settings, python-dotenv
- **Optimization:** ortools
- **Data:** datasets (HuggingFace), httpx
- **Optional:** datacommons-client (for facility locations)

### Frontend
- **UI Framework:** react, react-router-dom
- **Styling:** tailwind (v4.2), framer-motion
- **State:** zustand
- **Charts:** recharts
- **Maps:** mapbox-gl, react-map-gl, @deck.gl, maplibre-gl
- **Icons:** lucide-react
- **HTTP:** axios
- **Build:** vite, typescript (strict mode)
