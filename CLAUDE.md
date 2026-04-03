# CLAUDE.md — Supply Chain Intelligence Platform

## Project Goal
Build a portfolio-grade supply chain optimization web app targeting roles at McKinsey, BCG, Amazon, Apple Ops, and consulting firms. Full-stack: FastAPI backend, React TypeScript frontend, OR-Tools route optimization, Prophet ML forecasting.

## Tech Stack
- **Backend:** Python 3.11 + FastAPI + PostgreSQL + PostGIS + Redis + Celery
- **Frontend:** React 18 + TypeScript + Vite + Tailwind + Mapbox/Deck.gl
- **ML/Optimization:** Prophet + scikit-learn + Google OR-Tools + PuLP
- **Data:** FRED/EIA/BLS APIs, USGS minerals, Alpha Vantage, web scraping (ThomasNet, LME)
- **Infra:** Docker Compose (dev), Railway/Render (prod)

## Code Style & Conventions
- **Python:** PEP 8, type hints (use `from typing import`), docstrings on public functions
- **TypeScript:** strict mode, interface-first design, absolute imports from `@/`
- **Git:** feat/fix/refactor/docs prefixes, atomic commits, squash before merge to main
- **Env variables:** `.env.example` tracked, `.env` gitignored, load via `python-dotenv` and `vite.config.ts`
- **API routes:** Prefix with `/api/v1/`, return JSON with `{status, data, error}` schema

## Folder Structure (from plan)
```
backend/app/{api, models, ml, optimization, scrapers, core}
frontend/src/{pages, components, store, hooks}
data/{raw, processed, models}, notebooks, docker-compose.yml
```

## Key Implementation Details
1. **Auth:** JWT tokens, store in httpOnly cookies (not localStorage)
2. **Database:** Alembic migrations in `backend/migrations`, seed scripts in `backend/seeds`
3. **Celery:** Schedule price data pulls daily (FRED, EIA, Alpha Vantage) via Redis broker
4. **Maps:** Deck.gl for 3D arcs (supply routes), Mapbox GL for base layer, US-only bounds
5. **Optimization:** OR-Tools Vehicle Routing Problem for multi-objective (cost+time+CO2)
6. **ML Models:** Prophet trained per-material, serialized as `.pkl` in `data/models/`

## Startup Commands
```bash
docker compose up -d               # Start services
python backend/manage.py seed      # Load 200 materials, 25 hubs, 100+ suppliers
cd frontend && npm run dev         # React dev server on 3000
# FastAPI on 8000, Postgres 5432, Redis 6379
```

## Testing & Verification
- API tests: `pytest backend/tests` (use pytest-asyncio for async endpoints)
- Frontend tests: Vitest in `frontend/__tests__`
- Manual: Register → see factory pin on map → add to cart → checkout triggers VRP solver
- Check `/api/v1/docs` for interactive API documentation

## Commit Examples
- `feat: add OR-Tools VRP solver for multi-objective route optimization`
- `feat: integrate FRED API for commodity price forecasting`
- `fix: handle missing supplier data in risk score calculation`
- `refactor: consolidate Prophet model training into service layer`
- `docs: add architecture diagram to README`

## Known Data Sources
- **FRED:** `https://fred.stlouisfed.org/` (free API key, commodity prices)
- **EIA:** `https://www.eia.gov/opendata/` (energy costs by region)
- **BLS:** `https://www.bls.gov/developers/` (labor costs, no auth)
- **Alpha Vantage:** metals like Cu, Al, Au (free tier 5 req/min)
- **USGS Minerals:** free CSVs on rare earth / lithium production

## Differentiators (Resume Impact)
- Multi-objective VRP with Pareto frontier visualization
- Supply chain digital twin (what-if scenario simulator)
- Prophet forecasting with FRED exogenous regressors
- Monte Carlo delivery time confidence intervals
- Carbon footprint tracking (ESG angle)
