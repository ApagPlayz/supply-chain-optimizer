# Technology Stack
_Last updated: 2026-04-15_

## Summary
Full-stack supply chain optimization platform with a Python/FastAPI backend and a React/TypeScript frontend. The backend runs Google OR-Tools VRP solving and a two-model ML layer (scikit-learn) on top of SQLite in development and PostgreSQL in production. The frontend uses Vite, Tailwind CSS v4, Mapbox GL, and Deck.gl for interactive route visualization.

---

## Languages

**Backend:**
- Python 3.11 (pinned in `backend/Dockerfile`: `FROM python:3.11-slim`)

**Frontend:**
- TypeScript 5.9 (`~5.9.3` in `frontend/package.json`)
- Target: ES2023 (`frontend/tsconfig.app.json`)
- JSX: `react-jsx` transform (no need to import React in every file)

---

## Runtime & Environment

**Backend runtime:** CPython 3.11, managed via `venv` in `backend/venv/`

**Package manager (backend):** pip
- Production lockfile: `backend/requirements.txt` (pinned versions)
- Minimal/dev install: `backend/requirements_minimal.txt` (unpinned, used for local dev)

**Package manager (frontend):** npm
- Lockfile: `frontend/package-lock.json` (present, committed)

**Node version:** Not pinned (no `.nvmrc`). Vite 8 requires Node 18+.

---

## Backend Frameworks & Libraries

**Web framework:**
- `fastapi==0.104.1` — async REST API, dependency injection, Pydantic schema validation
- `uvicorn[standard]==0.24.0` — ASGI server; `--reload` used in dev

**Database ORM:**
- `sqlalchemy==2.0.23` — declarative ORM; sync session via `SessionLocal`
- `alembic==1.13.0` — schema migrations (`backend/migrations/`)

**Database drivers:**
- `psycopg[binary]==3.3.3` — PostgreSQL driver (production / Docker Compose)
- SQLite via Python stdlib — development default (`supply_chain.db`)

**Config / validation:**
- `pydantic==2.5.0`
- `pydantic-settings==2.1.0` — `Settings` class loaded from `.env` (`backend/app/core/config.py`)
- `python-dotenv==1.0.0`

**Authentication:**
- `python-jose[cryptography]==3.3.0` — JWT (HS256)
- `passlib[bcrypt]==1.7.4` + `bcrypt==4.1.1` — password hashing

**HTTP clients:**
- `httpx==0.25.1` — async HTTP (FRED, Nexar, EasyPost, etc.)
- `requests==2.31.0` — sync HTTP (legacy Celery tasks in `backend/app/scrapers/data_pipeline.py`)

**Optimization:**
- `ortools==9.7.2996` — Google OR-Tools VRP solver (multi-objective, 4 strategies: cheapest/fastest/greenest/balanced)
- `pulp==2.7.0` — MILP sourcing solver (Stage 1: component-to-distributor assignment)

**Machine learning:**
- `scikit-learn==1.3.2` — LogisticRegression (regime model), Ridge, RandomForest, GradientBoosting, MLP (lead time)
- `pandas==2.1.2` — FRED feature engineering, time-series manipulation
- `numpy==1.26.2`
- `joblib` — model persistence to `backend/data/ml_models/*.joblib`
- `fredapi` — FRED (Federal Reserve Economic Data) Python client

**Background tasks / scheduling:**
- `celery==5.3.4` — task queue (daily price pulls, weekly Prophet retraining)
- `redis==5.0.1` — Celery broker + result backend

**Data pipeline:**
- `datasets` (HuggingFace) — pulls `mdnh/electronic-components-supply-chain` dataset in `backend/seeds/seed_db.py`

**Forecasting (legacy / partially integrated):**
- `prophet==1.1.4` — time-series demand forecasting (Celery task in `backend/app/ml/prophet_forecaster.py`, weekly retrain scheduled)

**Utilities:**
- `beautifulsoup4==4.12.2` — HTML parsing

**Testing:**
- `pytest==7.4.3`
- `pytest-asyncio==0.23.0`

---

## Frontend Frameworks & Libraries

**Core:**
- `react==19.2.4` + `react-dom==19.2.4`
- `react-router-dom==7.1.1` — client-side routing

**Build tooling:**
- `vite==8.0.1` — bundler and dev server (proxy: `/api` → `http://localhost:8000`)
- `@vitejs/plugin-react==6.0.1` — Babel-based Fast Refresh

**Styling:**
- `tailwindcss==4.2.2` — utility CSS (v4 PostCSS plugin: `@tailwindcss/postcss`)
- `postcss==8.5.8` + `autoprefixer==10.4.27`
- `framer-motion==12.38.0` — animation

**State management:**
- `zustand==5.0.12` — lightweight store (`frontend/src/store/`)

**Maps & visualization:**
- `mapbox-gl==3.21.0` — base map tiles
- `maplibre-gl==5.22.0` — open-source alternative (both present)
- `react-map-gl==8.1.0` — React bindings for Mapbox/MapLibre
- `@deck.gl/react==9.2.11` + `@deck.gl/layers==9.2.11` + `deck.gl==9.2.11` — WebGL overlays (ScatterplotLayer, ArcLayer for routes)
- `recharts==3.8.1` — bar/line charts for price comparison and risk analysis

**HTTP:**
- `axios==1.14.0` (devDependency — used at runtime via `frontend/src/services/api.ts`)

**Auth utilities:**
- `jwt-decode==4.0.0` — decode JWT on frontend
- `js-cookie==3.0.5` — cookie access

**Forms & validation (devDependencies, available at runtime):**
- `@hookform/resolvers==5.2.2` — react-hook-form adapter
- `zod==4.3.6` — schema validation

**Data fetching (devDependency, available at runtime):**
- `@tanstack/react-query==5.96.2` — server state caching

**Icons:**
- `lucide-react==1.7.0`

**Linting:**
- `eslint==9.39.4` — flat config (`frontend/eslint.config.js`)
- `typescript-eslint==8.57.0`
- `eslint-plugin-react-hooks==7.0.1`
- `eslint-plugin-react-refresh==0.5.2`

---

## Database

| Environment | Database | Connection |
|-------------|----------|------------|
| Development | SQLite (`backend/supply_chain.db`) | `sqlite:///./supply_chain.db` (default in `config.py`) |
| Production (Docker) | PostgreSQL 16-alpine | `DATABASE_URL` env var |

Schema managed by Alembic (`backend/migrations/`). `Base.metadata.create_all()` also called at server startup for dev convenience.

---

## Infrastructure

**Containerization:** Docker Compose (`docker-compose.yml`) — 4 services:
- `db` — postgres:16-alpine on port 5432
- `redis` — redis:7-alpine on port 6379
- `backend` — Python 3.11-slim on port 8000
- `celery_worker` — same image, runs `celery -A app.core.celery_app worker`

**Celery beat schedules** (defined in `backend/app/core/celery_app.py`):
- Daily price pull: `pipeline.run_full_pipeline` at 06:00 UTC
- Weekly forecast retrain: `ml.train_all_forecasts` every Sunday 02:00 UTC

---

## Configuration

All settings loaded by `backend/app/core/config.py` (`pydantic-settings`). Source: `.env` file.

Key variables:
- `DATABASE_URL` — SQLAlchemy connection string
- `REDIS_URL` — Celery broker
- `SECRET_KEY` — JWT signing
- `MAPBOX_API_KEY` — map tile rendering (frontend)
- `FRED_API_KEY` — macro stress ML model (optional)
- `NEXAR_CLIENT_ID` / `NEXAR_CLIENT_SECRET` — live component pricing
- `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` — DigiKey API v4
- `OEMSECRETS_API_KEY` — 40+ distributors aggregate pricing
- `TRUSTEDPARTS_API_KEY` — authorized distributor data
- `EASYPOST_API_KEY` — real carrier transit time estimates
- `SUPPLYMAVEN_API_KEY` — macro disruption intelligence
- `EIA_API_KEY` / `ALPHA_VANTAGE_API_KEY` — energy and metals pricing
- `OPENWEATHER_API_KEY` — weather data

Template: `.env.example` at project root.

---

## ML Model Artifacts

Stored in `backend/data/ml_models/` (gitignored). Regenerate with:
```bash
cd backend && python -m seeds.train_ml_models
```

Files:
- `regime.joblib` — LogisticRegression pipeline (FRED macro stress)
- `lead_time.joblib` — dict of 4 fitted models (Ridge, RF, GBM, MLP)
- `feature_cols.joblib` — ordered feature column list for inference
- `metrics.joblib` — RMSE/MAE/R² + best model name + current stress probability

---

*Stack analysis: 2026-04-15*
