# Supply Chain Intelligence Platform

A portfolio-grade full-stack web application for optimizing material procurement in tech manufacturing. Targets roles at McKinsey, BCG, Amazon, Apple, and consulting firms.

## Features

- **Multi-Objective Route Optimization** — Minimize cost + time + carbon footprint simultaneously using Google OR-Tools
- **ML Price Forecasting** — Prophet models with FRED/EIA exogenous regressors for 90-day commodity predictions
- **Supply Chain Digital Twin** — Monte Carlo scenario simulator (tariffs, port closures, supplier failures)
- **Interactive Map** — 3D Deck.gl arc visualization of supply routes across US production hubs
- **Supplier Risk Scoring** — Composite score from financial health, geographic risk, weather exposure
- **ESG Tracking** — Carbon footprint and ESG dashboard
- **Real-time Data Pipeline** — Celery tasks pull from FRED, EIA, BLS, Alpha Vantage, OpenWeather APIs

## Tech Stack

**Backend:** Python 3.11 + FastAPI + PostgreSQL + PostGIS + Redis + Celery  
**Frontend:** React 18 + TypeScript + Vite + Tailwind + Mapbox/Deck.gl  
**ML:** Prophet + scikit-learn + OR-Tools + PuLP  
**Data:** FRED, EIA, BLS, USGS, Alpha Vantage, ThomasNet scraping  
**Deployment:** Docker Compose (dev), Railway/Render (prod)

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+
- Python 3.11+ (for local development)

### Run with Docker

```bash
# Start services (FastAPI, PostgreSQL, Redis, Celery)
docker compose up

# In a new terminal, initialize database
docker compose exec backend alembic upgrade head
docker compose exec backend python -m backend.seeds.seed_db

# Frontend runs on http://localhost:3000
cd frontend && npm run dev
```

API docs available at `http://localhost:8000/docs`

### Local Development (without Docker)

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Project Structure

```
logistics-project/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routers
│   │   ├── models/        # SQLAlchemy ORM
│   │   ├── ml/            # Prophet, forecasting
│   │   ├── optimization/  # OR-Tools, routing
│   │   ├── scrapers/      # FRED, EIA, ThomasNet
│   │   └── core/          # config, security, celery
│   ├── migrations/        # Alembic migrations
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/         # Login, Dashboard, Map, Scheduler, Cart, Checkout
│   │   ├── components/    # Reusable UI components
│   │   ├── store/         # Zustand auth/cart stores
│   │   ├── services/      # API client
│   │   └── hooks/         # Custom React hooks
│   └── package.json
├── data/
│   ├── raw/               # USGS, BLS CSVs
│   ├── processed/         # Cleaned materials catalog
│   └── models/            # Serialized Prophet models
└── docker-compose.yml
```

## Key Endpoints

### Authentication
- `POST /api/v1/auth/register` — Register factory manager
- `POST /api/v1/auth/login` — Login and get JWT token
- `GET /api/v1/auth/me` — Get current user

### Materials & Forecasting
- `GET /api/v1/materials` — List 200 tech materials
- `GET /api/v1/materials/{id}/forecast` — 90-day price forecast
- `GET /api/v1/materials/{id}/suppliers` — Suppliers for material

### Optimization
- `POST /api/v1/optimize/vrp` — Multi-objective route optimization
- `POST /api/v1/optimize/scenario` — Monte Carlo what-if analysis

### Map & Hubs
- `GET /api/v1/hubs` — US production hubs with specialization
- `POST /api/v1/hubs/nearby` — Find suppliers near factory

## Data Sources

| Source | Data | Frequency |
|--------|------|-----------|
| FRED API | Commodity prices, PPI, economic indicators | Daily |
| EIA API | Energy costs by region | Daily |
| BLS API | Regional labor costs | Monthly |
| Alpha Vantage | Metals price history (Cu, Al, Au, Ag) | Daily |
| USGS Minerals | Rare earth/lithium supply | Static |
| OpenWeatherMap | Weather disruption risk | Real-time |
| ThomasNet | US manufacturer directories | Weekly scrape |

## Resume Highlights

- "Engineered multi-objective VRP solver (OR-Tools) minimizing cost, lead time, and CO2e simultaneously"
- "Built Prophet + FRED API commodity forecasting with exogenous macroeconomic regressors"
- "Designed Monte Carlo simulation for delivery time confidence intervals and risk analysis"
- "Implemented supply chain digital twin with parameterized what-if scenarios"
- "Integrated 10+ free APIs and web scrapers for 200 tech manufacturing materials"

## Development Roadmap

- [ ] **Phase 1** — Auth, DB, Docker, FastAPI foundation ✓
- [ ] **Phase 2** — Interactive US map (Deck.gl + Mapbox)
- [ ] **Phase 3** — Material scheduler + data pipeline (Celery)
- [ ] **Phase 4** — ML forecasting (Prophet) + recommendations
- [ ] **Phase 5** — Cart + VRP optimization + Monte Carlo
- [ ] **Phase 6** — Digital twin simulator + ESG dashboard + PDF export

## Contributing

See CLAUDE.md for code style, git conventions, and architecture patterns.

## License

MIT

---

Built with Claude Code. For questions or feedback, check the project issues.
