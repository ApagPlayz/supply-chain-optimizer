# External Integrations
_Last updated: 2026-04-15_

## Summary
The platform integrates with six categories of external services: component pricing/inventory APIs, macroeconomic data feeds, shipping/logistics APIs, mapping services, a static HuggingFace dataset for seeding, and background infrastructure (Celery + Redis). All external API keys are optional at runtime — every integration gracefully degrades to a fallback when its key is absent.

---

## Component Pricing & Inventory APIs

### Nexar / Octopart (GraphQL)
- **Purpose:** Live electronic component pricing and distributor offers across all major distributors
- **Client:** `backend/app/core/clients/nexar_client.py`
- **Endpoint:** `https://api.nexar.com/graphql/`
- **Auth:** OAuth2 client credentials → Bearer token (auto-refreshed); token URL: `https://identity.nexar.com/connect/token`
- **Env vars:** `NEXAR_CLIENT_ID`, `NEXAR_CLIENT_SECRET`
- **Free tier:** 1,000 part lookups lifetime on evaluation account
- **Paid tiers:** 2,000/month Standard; 15,000/month Pro
- **Fallback:** HuggingFace static dataset (791 components, 8,731 offers)
- **Status:** Client implemented; currently seeded from static dataset, live integration optional

### DigiKey API v4
- **Purpose:** Product search + bonded inventory by warehouse location (feeds location-aware VRP stock data)
- **Client:** `backend/app/core/clients/digikey_client.py`
- **Endpoints:** `https://api.digikey.com/products/v4/search` (prod), `https://sandbox-api.digikey.com` (sandbox)
- **Auth:** OAuth2 client credentials; token URL: `https://api.digikey.com/v1/oauth2/token`
- **Env vars:** `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`, `DIGIKEY_SANDBOX` (bool)
- **Free tier:** 1,000 searches/day, no credit card required
- **Status:** Client implemented, not yet wired into live request path

### OEMsecrets
- **Purpose:** Aggregate pricing from 40+ distributors in a single API call (breadth beyond Nexar's major distributors)
- **Client:** `backend/app/core/clients/oemsecrets_client.py`
- **Auth:** API key
- **Env vars:** `OEMSECRETS_API_KEY`
- **Access:** Approval-based; apply at https://www.oemsecrets.com/api
- **Status:** Client implemented, not yet wired into live request path

### TrustedParts
- **Purpose:** Authorized distributor data only (franchise-only sourcing use case)
- **Client:** `backend/app/core/clients/trustedparts_client.py`
- **Auth:** API key
- **Env vars:** `TRUSTEDPARTS_API_KEY`
- **Free tier:** Completely free; registration at https://www.trustedparts.com/docs/
- **Status:** Client implemented, not yet wired into live request path

---

## Macroeconomic Data Feeds

### FRED (Federal Reserve Economic Data)
- **Purpose:** Six semiconductor supply chain series used to train and run the macro stress regime ML model
- **Client (ML training):** `backend/app/ml/fred_client.py` — uses `fredapi` Python package
- **Client (price history):** `backend/app/core/data_fetcher.py` — uses `httpx` directly; also `backend/app/scrapers/data_pipeline.py` (Celery task)
- **Endpoint:** `https://api.stlouisfed.org/fred/series/observations`
- **Auth:** API key as query parameter
- **Env vars:** `FRED_API_KEY`
- **Free tier:** Free; register at https://fred.stlouisfed.org/docs/api/api_key.html
- **Series consumed:**
  - `PCU33443344` — PPI: Semiconductor & Electronic Component Manufacturing
  - `CAPUTLG3344S` — Capacity Utilization: Semiconductors (%)
  - `ISRATIO` — Total Business Inventory-to-Sales Ratio
  - `IPG3344S` — Industrial Production: Semiconductors
  - `IZ3344` — Import Price Index: Electronic Components
  - `TSIFRGHT` — Freight Transportation Services Index
- **Fallback:** If `FRED_API_KEY` is not set, stress probability defaults to `0.0` (no regime surcharge applied)

### Alpha Vantage
- **Purpose:** Metals spot prices (copper, aluminum, gold, silver) and commodity prices for the price history Celery pipeline
- **Client:** `backend/app/core/data_fetcher.py` + `backend/app/scrapers/data_pipeline.py`
- **Endpoint:** `https://www.alphavantage.co/query`
- **Auth:** API key as query parameter
- **Env vars:** `ALPHA_VANTAGE_API_KEY`
- **Free tier:** Free API key available at https://www.alphavantage.co/support/#api-key
- **Supported symbols:** `COPPER`, `ALUMINUM`, `WTI`, `BRENT`, `NATURAL_GAS`, `XAUUSD`, `XAGUSD`
- **Fallback:** FRED is tried first; Alpha Vantage is the secondary fallback

### EIA (Energy Information Administration)
- **Purpose:** US retail electricity prices — energy cost component of supply chain model
- **Client:** `backend/app/scrapers/data_pipeline.py` (Celery task, `EIA_BASE = "https://api.eia.gov/v2/electricity/retail-sales/data"`)
- **Auth:** API key
- **Env vars:** `EIA_API_KEY`
- **Status:** Wired in data pipeline Celery task; key is optional with graceful skip

### OpenWeather
- **Purpose:** Weather data (listed in config; no active client found in codebase)
- **Env vars:** `OPENWEATHER_API_KEY`
- **Status:** Config placeholder only — no client implemented

---

## Shipping & Logistics APIs

### EasyPost SmartRate
- **Purpose:** Real carrier transit time estimates to replace haversine-based ETA in the VRP cost matrix
- **Client:** `backend/app/core/clients/easypost_client.py`
- **Endpoint:** `https://api.easypost.com/v2`
- **Auth:** HTTP Basic Auth with API key as username
- **Env vars:** `EASYPOST_API_KEY`
- **Free tier:** 500 SmartRate calls free, then $0.03/call; 3,000 free labels/month
- **Integration point:** `backend/app/optimization/solve.py` — when key is set, replaces haversine ETA with p50/p75/p90 carrier transit confidence intervals
- **Fallback:** Haversine distance-based ETA (`backend/app/optimization/costs.py`) when key is absent
- **Status:** Client implemented, conditional wiring in optimizer

### SupplyMaven
- **Purpose:** Macro disruption intelligence — GDI scores, disruption alerts, tariff data — feeds the Digital Twin scenario simulator
- **Client:** `backend/app/core/clients/supplymaven_client.py`
- **Auth:** API key
- **Env vars:** `SUPPLYMAVEN_API_KEY`
- **Pricing:** $499/month Pro (free tier availability unclear)
- **Status:** Client implemented; integration into Digital Twin page optional

---

## Mapping & Visualization

### Mapbox GL
- **Purpose:** Base map tiles for the interactive route/distributor map (`frontend/src/pages/MapPage.tsx`, `frontend/src/pages/CheckoutPage.tsx`)
- **SDK:** `mapbox-gl==3.21.0` + `react-map-gl==8.1.0`
- **Auth:** Public API token passed to map component
- **Env vars:** `MAPBOX_API_KEY` (surfaced to frontend — note: this is a public token, not a secret)
- **Alternative:** `maplibre-gl==5.22.0` is also installed for open-source tile server fallback

---

## Static Data Sources

### HuggingFace Dataset (mdnh/electronic-components-supply-chain)
- **Purpose:** Primary seed data — 791 components, 8,731 distributor offers, 92 real distributors
- **SDK:** `datasets` (HuggingFace Python library)
- **Seeding script:** `backend/seeds/seed_db.py`
- **Access:** Public dataset, no API key required
- **Usage:** Run once to populate the SQLite/PostgreSQL database; not queried at runtime
- **Auth:** None required (public dataset)

### Data Commons (Google) — EIA-860 + EPA Facilities
- **Purpose:** 33,884 US power plants and 10,512 EPA reporting facilities used as delivery destination nodes on the map
- **Env vars:** `EIA_API_KEY` (separate from EIA price data; different endpoint)
- **Note:** Documented in `CLAUDE.md`; no active client found in `backend/app/core/clients/` — integration may be partially implemented

---

## Background Infrastructure

### Redis
- **Purpose:** Celery message broker + task result backend
- **Image:** `redis:7-alpine` (Docker Compose)
- **Connection:** `REDIS_URL` env var (default: `redis://localhost:6379`)
- **Used by:** `backend/app/core/celery_app.py`, all Celery workers

### Celery
- **Purpose:** Async task queue for scheduled data pulls and ML retraining
- **App:** `backend/app/core/celery_app.py`
- **Registered task modules:**
  - `app.scrapers.data_pipeline` — FRED, Alpha Vantage, EIA price pulls
  - `app.ml.forecast_tasks` — Prophet forecast retraining
- **Beat schedule:**
  - Daily 06:00 UTC: `pipeline.run_full_pipeline`
  - Weekly Sunday 02:00 UTC: `ml.train_all_forecasts`

---

## Authentication (Internal)

- **Standard:** JWT (HS256) via `python-jose`; tokens returned on login
- **Storage:** Frontend stores token in cookie (`js-cookie`); decoded with `jwt-decode`
- **Expiry:** `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30 min)
- **Endpoints:** `POST /api/v1/auth/login`, `POST /api/v1/auth/register`, `POST /api/v1/auth/demo`
- **Implementation:** `backend/app/api/auth.py`, `backend/app/core/security.py`

---

## Environment Variable Reference

| Variable | Service | Required | Notes |
|----------|---------|----------|-------|
| `DATABASE_URL` | PostgreSQL | Prod only | Defaults to SQLite in dev |
| `REDIS_URL` | Redis/Celery | Prod only | Defaults to `redis://localhost:6379` |
| `SECRET_KEY` | JWT | Yes | Change from default in prod |
| `MAPBOX_API_KEY` | Mapbox | Yes (maps) | Public token |
| `FRED_API_KEY` | FRED | Optional | ML regime model; defaults stress to 0.0 |
| `NEXAR_CLIENT_ID` / `NEXAR_CLIENT_SECRET` | Nexar | Optional | Live pricing |
| `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` | DigiKey | Optional | Live inventory |
| `OEMSECRETS_API_KEY` | OEMsecrets | Optional | Aggregate pricing |
| `TRUSTEDPARTS_API_KEY` | TrustedParts | Optional | Auth distributor data |
| `EASYPOST_API_KEY` | EasyPost | Optional | Real transit times |
| `SUPPLYMAVEN_API_KEY` | SupplyMaven | Optional | Disruption intelligence |
| `EIA_API_KEY` | EIA | Optional | Energy prices |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | Optional | Metals prices |
| `OPENWEATHER_API_KEY` | OpenWeather | Optional | No client implemented |
| `DIGIKEY_SANDBOX` | DigiKey | Optional | Bool; use sandbox API |

---

*Integration audit: 2026-04-15*
