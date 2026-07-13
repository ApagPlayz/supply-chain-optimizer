# Electronics Supply Chain Optimizer

[![CI](https://github.com/ApagPlayz/supply-chain-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/ApagPlayz/supply-chain-optimizer/actions/workflows/ci.yml)

A full-stack supply chain intelligence platform for electronic component procurement. Built on real market data: **791 components, 92 distributors, 8,176 price offers** — a static 2024 snapshot originally collected via the Nexar API (which aggregates Octopart), redistributed on HuggingFace under CC-BY-4.0. It is real, but it is a **frozen snapshot, not a live feed** ([docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md)).

**Live demo flow:** Login → browse components → add to cart → run multi-objective VRP optimization → explore resilience scenarios.

![Dashboard](docs/screenshots/sc-dashboard.png)

---

## What it does

**For a PCB manufacturer sourcing a BOM of electronic components across 92 real distributors:**

| Feature | Technical approach |
|---------|-------------------|
| Supplier selection | CP-SAT MILP (OR-Tools) — minimize landed cost under stock/MOQ constraints |
| Route optimization | TSP with OR-Tools routing — PATH_CHEAPEST_ARC + Guided Local Search |
| 4 Pareto-distinct strategies | Multi-objective weighted sum (cost / time / carbon) — each provably distinct |
| Delivery uncertainty | Monte Carlo simulation (1,000 scenarios) → P10/P50/P90 ETA bands |
| Network fragility | Graph ML: Fiedler algebraic connectivity, betweenness centrality, HHI, k-core decomposition |
| Resilience scenarios | Distributor failure cascade, geopolitical risk overlay, delivery target optimization |
| Demand forecasting | Prophet + FRED macro regressors → 12-week horizon with stockout warnings |
| Live risk feeds | GPR index, ACLED conflict data, IMF PortWatch port congestion, FRED freight indices |

---

## Dollar-denominated impact

Every headline metric is paired with a concrete financial interpretation, derived
from real computed quantities — never an invented figure. The conversions are
surfaced live in the dashboard (resilience banner, benchmark strip, forecast and
holding-cost tooltips) and summarized here.

| Metric | Where it comes from | Dollar translation |
|--------|---------------------|--------------------|
| **CVaR-95** (tail-risk) | Mean emergency-procurement cost multiplier over the worst-5% of 1,000 Monte Carlo cascade scenarios (`graph/simulation.py`) | **"$X of procurement spend at risk"** = real baseline BOM spend × (CVaR-95 − 1). Computed per BOM in `resilience.py` (`procurement_spend_at_risk_usd`) and shown on the Resilience page; aggregated per reference BOM on the Benchmark page (`baseline_spend_at_risk_usd`). **Caveat — read this before trusting the number:** the *spend* side is real, but the *probability* side is not calibrated. Distributor failure probability is currently derived from betweenness centrality, so the most central distributor fails in essentially every scenario and CVaR-95 saturates near 1.15. The dollar figure is therefore closer to "real spend × an assumed 15% surcharge" than to a data-derived tail. Grounding these probabilities in a cited base rate is a known open item. |
| **Optimizer cost delta** | Graph-aware vs baseline total landed cost across the 10 reference BOMs (`benchmark.py`) | **"$Y saved per BOM run"** = mean(graph-aware − baseline `total_cost_usd`). Computed live as `cost_delta_usd` and shown on the Benchmark page (negative = saved). Surfaced as a real, run-dependent figure rather than a fixed claim — on the current reference set the graph-aware delta sits near the ±2% noise floor, which the page labels honestly. |
| **Forecast WAPE** | Walk-forward backtest (3 rolling origins, 12-month horizon): Prophet **2.5%** vs seasonal-naive **4.4%** — skill score **+42.7%** — on Census M3 `A34SNO` (Manufacturers' New Orders: Computers & Electronic Products), 197 monthly obs ([docs/FORECAST_BACKTEST.md](docs/FORECAST_BACKTEST.md)) | **"≈ N weeks of safety stock at $W carrying cost."** Safety stock ≈ z·WAPE of horizon demand at a 95% service level (z = 1.645). Prophet's edge cuts the buffer from ≈0.87 → ≈0.50 weeks (**≈0.37 weeks avoided**). At a 25%/yr carrying cost, that is **≈ $1.8k/yr saved per $1M of annual component spend** (1 wk ≈ $19.2k inventory → $4.8k/yr to carry × 0.37 wk). Shown in the Component Browser forecast tooltip. **Caveat:** this WAPE is measured on an *aggregate industry series*, not on the per-part demand the app actually serves — see below. |

### Conversion assumptions & citations

- **Inventory carrying cost = 25%/yr.** Reused from the existing optimizer constant
  `ANNUAL_HOLDING_RATE = 0.25` (`backend/app/optimization/costs.py`), cited to
  **Gartner IT Supply Chain Benchmarks 2022** (electronics annual holding rate). The
  same rate already drives the per-route holding cost shown at checkout. Industry
  ranges are typically 20–25%/yr (Richardson, *Harvard Business Review*; APICS).
- **Service level z = 1.645** (95%, one-sided normal) for the safety-stock buffer.
  WAPE is used as a σ/μ forecast-error proxy over the planning horizon — a standard
  textbook safety-stock framing (Silver, Pyke & Peterson, *Inventory Management and
  Production Planning*).
- **CVaR-95 → dollars is half data-derived, and I want to be precise about which
  half.** The *spend* side is real: it multiplies by the real BOM spend (sum of each
  line's average real offer price). The *probability* side is not calibrated —
  distributor failure probability is proxied by betweenness centrality
  (`graph/simulation.py`), which is a structural importance score, not a likelihood.
  The practical effect is that the most central distributor fails in nearly every
  scenario and the tail multiplier saturates around 1.15. Earlier drafts of this
  README called this "fully data-derived." **That was an overstatement and it has
  been corrected.**

### What this model can't do

Stated up front, because an interviewer will find these anyway and it is better that
they hear it from me:

- **The demand forecast that is *served* is not the one that was *backtested*.** The
  backtest above runs on `A34SNO`, a real aggregate Census series. The per-part
  demand in the app is derived from inventory (`total_stock / 52 × risk_multiplier`,
  `seeds/train_forecasts.py`) and shares one macro curve across all 791 parts. So the
  2.5% WAPE is an honest measurement of Prophet on a real industry series — it is
  **not** evidence that per-part forecasts are 2.5% accurate. That number is unmeasured,
  because per-part ground-truth demand is not something this public dataset contains.
- **Disruption probabilities are structural, not empirical** (see the CVaR caveat above).
- **The lead-time ML model is trained on n=75 observations** from a single day and a
  single distributor. Any R² quoted off a 15-point test split is not a number I would
  defend; the weekly collector (`.github/workflows/collect-lead-times.yml`) exists to
  grow this panel until it is.
- **Prices are a frozen 2024 snapshot**, so nothing here reflects today's market.

See [docs/IMPACT_FRAMING.md](docs/IMPACT_FRAMING.md) for the full derivations.

---

## Quick Start (no Docker required)

See **[QUICK_START.md](QUICK_START.md)** for step-by-step setup.

**TL;DR:**
```bash
# Terminal 1 — backend
cd backend && source venv/bin/activate
python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open http://localhost:5173 → click **Demo Login**.

---

## Tech Stack

**Backend:** Python 3.11 · FastAPI · SQLAlchemy · SQLite (dev) / PostgreSQL (prod) · OR-Tools · NetworkX · Prophet · scikit-learn  
**Frontend:** React 18 · TypeScript · Vite · Tailwind CSS · Recharts · Zustand  
**Algorithms:** CP-SAT MILP, TSP, Monte Carlo simulation, Spectral Graph Theory  
**Data:** Nexar/Octopart static 2024 snapshot (real component pricing), DigiKey API (live lead times), FRED, IMF PortWatch, GPR index, ACLED (needs a key — reports as inactive without one)

---

## Architecture

```
frontend/src/
  pages/          Dashboard, Map, Scheduler, Cart, CheckoutPage, ResiliencePage, BenchmarkPage
  components/     ScenarioCard, MonteCarloChart, BOMImpactTable, DeltaCard, NavBar
  store/          Zustand: authStore, cartStore, optimizeStore
  services/api.ts Axios client for all backend endpoints

backend/app/
  api/            FastAPI routers: auth, cart, optimize, resilience, graph, feeds, forecasts
  optimization/   CP-SAT sourcing MILP, OR-Tools TSP, cross-dock facility location
  graph/          NetworkX bipartite supply graph, Fiedler curve, centrality metrics
  feeds/          Live data fetchers: GPR, ACLED, IMF PortWatch, FRED freight
  ml/             Prophet demand forecasting, sklearn lead-time prediction, FRED regime model
  cache.py        SHA256-keyed scenario cache, 1h TTL, background cleanup
  supply_chain.db SQLite — 791 components, 92 distributors, 8,176 price offers (real data)
```

---

## Screenshots

| VRP Optimization (4 strategies) | Resilience Dashboard |
|---|---|
| ![Checkout](docs/screenshots/sc-checkout.png) | ![Resilience](docs/screenshots/sc-resilience.png) |

---

## Key API Endpoints

```
POST /api/v1/auth/demo                       # one-click demo login
GET  /api/v1/components                      # 791 real electronic components
POST /api/v1/optimize/vrp                    # 4-strategy VRP: cheapest/fastest/greenest/balanced
GET  /api/v1/graph/metrics                   # Fiedler value, centrality, HHI, k-core
POST /api/v1/resilience/distributor-failure  # simulate distributor outage -> cost/ETA/risk delta
POST /api/v1/resilience/geopolitical-risk    # overlay GPR spike -> affected components
POST /api/v1/resilience/delivery-target      # "who can hit 14 days?" -> supplier capability list
GET  /api/v1/forecasts/all                   # Prophet 12-week demand forecast for all 791 components
GET  /api/v1/feeds/status                    # live feed status: GPR, ACLED, PortWatch, FRED
GET  /api/v1/benchmark/summary               # network resilience metrics snapshot
```

Full API reference: http://localhost:8000/docs (Swagger UI when running locally)  
Scenario API reference: [docs/SCENARIO_API.md](docs/SCENARIO_API.md)

---

## Tests

```bash
cd backend
source venv/bin/activate
pytest tests/ -q
# -> 291 passed, 2 skipped
```

Test coverage: optimization solver (sourcing, routing, cross-dock), graph metrics, ML models, resilience API, auth guards, feed integrations.

---

## Lint & type-check

CI runs a dedicated `backend-lint` job (ruff + mypy) alongside tests, plus `tsc -b`
for the frontend (part of `npm run build`). Config lives in `backend/pyproject.toml`.

```bash
cd backend
source venv/bin/activate
pip install -r requirements-dev.txt   # ruff + mypy, dev-only

ruff check app          # lint (E/F/I/UP/B core rules)
ruff format app --check # formatting — not yet wired into CI (see note below)
mypy app                 # type-check (non-strict)
```

Both `ruff check app` and `mypy app` are green today. Deliberately deferred, tracked
in `pyproject.toml` comments so they can be picked up later without fighting
in-flight edits elsewhere in the repo:

- **`ruff format`**: ~63 of 71 backend files would be reformatted (the codebase
  predates a formatter convention). Not added as a CI gate yet — running it would
  touch nearly every file. Run locally and land as its own PR when convenient.
- **Typing-modernization rules** (`UP006`, `UP035`, `UP037`, `UP045` — `List`/`Optional[X]`
  → `list`/`X | None`) and **import sorting** (`I001`): large, repo-wide, low-risk-but-
  noisy sweeps. Ignored in `[tool.ruff.lint]` for now; safe to re-enable and `--fix`
  once other in-flight branches land.
- **A handful of per-file rule ignores** in `app/ml/regime_model.py`, `app/ml/lead_time_model.py`,
  `app/optimization/recommendations.py`, `app/optimization/solve.py`,
  `app/optimization/sourcing.py`, `app/graph/simulation.py`,
  `app/core/clients/oemsecrets_client.py` — small, real lint findings (unused imports/vars,
  `zip()` without `strict=`, an unused loop variable) left untouched because those files
  are owned by concurrent work; see `[tool.ruff.lint.per-file-ignores]`.
- **mypy** is fully strict-by-default-off (`ignore_missing_imports`, no `--strict`) and
  has a `[[tool.mypy.overrides]]` block that turns off checking for ~22 modules — mostly
  `app/api/*` and `app/optimization/*` — where the codebase's untyped SQLAlchemy
  `Column(...)` declarative models (no `Mapped[...]` annotations) produce large numbers
  of `Column[T]` vs `T` false positives rather than real bugs. ~50 modules are fully
  type-checked today. Migrating `app/models/*` to SQLAlchemy 2.0 `Mapped[]` typing would
  let those overrides be removed.

---

## Interview Narrative

See [docs/RESILIENCE_INTERVIEW_GUIDE.md](docs/RESILIENCE_INTERVIEW_GUIDE.md) for the full demo walkthrough and talking points.

**The 30-second pitch:**

> "Supply chain resilience is a graph problem, so I measured it spectrally — and the
> measurement talked me out of my own thesis. I expected one dominant distributor and a
> network one failure from collapse. What the data actually says: DigiKey is the largest
> single distributor at **11.2%** of offers, not 40%; killing DigiKey outright orphans
> **zero** components and moves landed cost by **~0%**, because the per-line redundancy
> is genuinely there. The whole-graph Fiedler value is exactly 0.0 — but that's a floor
> by construction, since the graph fragments into 43 components. The number that means
> something is λ₂ = **0.238** on the giant component, which holds **95%** of the network:
> moderately connected, not fragile. The real single-point risk is the other 5% — the
> parts with no path into the main network at all. That's the list worth acting on."

*(An earlier version of this pitch claimed "DigiKey handles 40% of offers" and "12
components have no alternative source." Neither is true of this data. They are left
documented here rather than quietly deleted, because catching it is the more
interesting story than never having written it.)*

**Key talking points:**
- Fiedler value as a fragility metric — including *why the naive whole-graph reading of it is a trap* on a disconnected graph
- Monte Carlo shows distribution tails, not just means — that's where supply chain risk lives
- CP-SAT produces 4 Pareto-distinct strategies because cost, time, and carbon are not scalar multiples of each other
- Live geopolitical data overlay: GPR/PortWatch/FRED feeds inform the optimizer (ACLED is wired but needs a key — the UI labels it "Inactive" rather than faking a healthy feed)

---

## Data Sources

| Source | What it provides |
|--------|-----------------|
| Nexar / Octopart (**static 2024 snapshot**, via HuggingFace `mdnh/electronic-components-supply-chain`, CC-BY-4.0) | Real component pricing, stock levels, distributor offers (791 components, 92 distributors, 8,176 offers). Real data, but a **frozen snapshot** — not a live API feed. See [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md). |
| DigiKey API (**live**) | Real lead times, refreshed weekly by [`.github/workflows/collect-lead-times.yml`](.github/workflows/collect-lead-times.yml) |
| FRED (Federal Reserve) | Freight index, PPI, macro stress regime |
| ACLED | Conflict event counts by country (distributor risk) |
| IMF PortWatch | Port call frequency (congestion delay) |
| GPR Index | Geopolitical risk index (Chinese-origin component risk) |

---

## License

MIT
