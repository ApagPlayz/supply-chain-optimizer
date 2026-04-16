# Roadmap: Electronics Supply Chain Optimizer — Graph ML Extension

## Overview

This milestone extends a working supply chain route optimizer with three new
capabilities: a hardened security baseline, a Graph ML network risk engine, and live
macro data feeds — all converging on a benchmark dashboard that produces quantified,
defensible numbers for DS/ML interviews. The five phases are sequenced so each one
produces a demo-ready artifact before the next begins. Phase 1 removes blockers that
would embarrass a public demo. Phase 2 builds the graph risk engine that feeds Phase 3
(live signals) and Phase 4 (benchmark output). Phase 5 resurrects the broken Prophet
forecaster as an independent capability that depends only on the cleaned codebase from
Phase 1.

---

## Phases

- [ ] **Phase 1: Codebase Hardening** - Eliminate security vulnerabilities and orphaned pre-pivot artifacts so the codebase is safe to share and demo
- [ ] **Phase 2: Graph ML Network Risk Engine** - Build NetworkX bipartite supply graph with centrality, Fiedler, k-core, HHI, Monte Carlo cascade, and CP-SAT injection
- [ ] **Phase 3: Live Data Feeds** - Integrate GPR, ACLED, IMF PortWatch, and FRED freight signals with TTL caching and graceful degradation
- [ ] **Phase 4: Benchmark Dashboard** - Produce quantified A/B comparison (graph-aware vs baseline) with frontend visualization of Monte Carlo and Fiedler outputs
- [ ] **Phase 5: Prophet Demand Forecasting** - Resurrect broken forecaster ported to Component/DistributorOffer schema with 12-week horizon on Scheduler page

---

## Phase Details

### Phase 1: Codebase Hardening
**Goal**: The codebase is safe to share publicly and all pre-pivot orphans are removed or ported
**Depends on**: Nothing (first phase)
**Requirements**: HARD-01, HARD-02, HARD-03, HARD-04, HARD-05, HARD-06
**Success Criteria** (what must be TRUE):
  1. Server raises ValueError at startup if SECRET_KEY matches any known default string — JWT forgery is impossible on a deployed instance
  2. CORS allow_origins reads from env var and rejects cross-origin requests from unlisted domains
  3. Live-pricing and market-intelligence endpoints return 401 for unauthenticated callers
  4. Importing any file in the backend raises no ModuleNotFoundError — no references to the deleted Material model remain
  5. Demo login works without error on repeated calls — no duplicate db.add race condition
**Plans**: 3 plans

Plans:
- [x] 01-01: Security hardening — SECRET_KEY validation, CORS restriction, DEBUG default, auth guards on live-price endpoints
- [x] 01-02: Orphaned code removal — delete or port prophet_forecaster.py, forecast_tasks.py, data_pipeline.py to Component/DistributorOffer schema
- [x] 01-03: Bug fixes and debt — demo login duplicate-add fix, constants.py extraction, N+1 query fixes in /cart and /components

### Phase 2: Graph ML Network Risk Engine
**Goal**: A GraphState singleton loads at startup, computes all risk scores in < 2 s, and injects them as additive CP-SAT surcharges that produce measurably different routing decisions
**Depends on**: Phase 1
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04, GRAPH-05, GRAPH-06, GRAPH-07, GRAPH-08, GRAPH-09, GRAPH-10
**Success Criteria** (what must be TRUE):
  1. `GET /api/v1/graph/metrics` returns betweenness centrality, PageRank, k-core membership, HHI per category, single-source ratio, and Fiedler value (λ₂) for the live DB — all computed from real offer data
  2. Running `POST /api/v1/optimize/vrp` with graph_aware=true produces a different distributor selection than graph_aware=false on any BOM containing a high-centrality distributor — the surcharge is visible in the cost breakdown
  3. `POST /api/v1/graph/simulate` returns P10/P50/P90 BOM fulfillment rates and EVaR cost inflation at 95th percentile across N=1,000 Monte Carlo scenarios
  4. Server startup log shows graph build completed in under 2 seconds with node/edge counts confirming all 92 distributors and 791 components loaded
  5. Removing the top-betweenness distributor drops the reported Fiedler value by a measurable percentage — the resilience degradation curve is computable
**Plans**: 4 plans

Plans:
- [ ] 02-01: `app/graph/` module scaffold — GraphState singleton, builder.py (bipartite DiGraph from SQLite), __init__.py mirroring app/ml/ pattern, lifespan wiring in main.py [PARALLEL-SAFE with 02-02 after scaffold]
- [ ] 02-02: Centrality and structural metrics — stock-weighted betweenness, PageRank, k-core decomposition, HHI per category, Fiedler value (algebraic_connectivity), single-source edge flags; all cached on GraphState [depends on 02-01]
- [ ] 02-03: Monte Carlo cascade simulation — N=1,000 scenario sampler, SIR-style propagation over k-core subgraph, P10/P50/P90 fulfillment output, EVaR at 95th percentile, fixed random seed for reproducibility [depends on 02-02]
- [ ] 02-04: CP-SAT injection and graph API endpoints — additive node-weight surcharge on y[did] (betweenness) and edge surcharge on q[key] (single-source), graph_aware flag in optimize_bom(), GET /graph/metrics + POST /graph/simulate endpoints [depends on 02-02, 02-03]

### Phase 3: Live Data Feeds
**Goal**: Four external signals (GPR, ACLED, IMF PortWatch, FRED freight) refresh on schedule, degrade gracefully on outage, and visibly affect risk scores and lead time modifiers in the optimizer
**Depends on**: Phase 1
**Requirements**: FEED-01, FEED-02, FEED-03, FEED-04, FEED-05, FEED-06, FEED-07

**Note:** Phase 3 depends only on Phase 1 (clean codebase + auth guards). It is independent of Phase 2 and can be executed in parallel with Phase 2 by a second agent if needed. The feeds wire into the optimizer's risk weighting as additive modifiers alongside graph surcharges.

**Success Criteria** (what must be TRUE):
  1. Dashboard shows a freshness timestamp for each live feed — a user can see exactly when each signal was last fetched
  2. Running the optimizer with a BOM containing Chinese-origin components produces a higher risk surcharge when the current GPR Index is elevated vs. when it is at baseline — the feed visibly moves a number
  3. Killing all external API connectivity and reloading the app causes zero 500 errors — optimizer runs on static fallback scores and the UI labels each feed as [stale] or [unavailable]
  4. No API keys appear in the frontend bundle, browser devtools network tab, or git log
  5. APScheduler job refreshes all feeds on a 15-minute interval and logs completion with data freshness timestamps
**Plans**: 3 plans

Plans:
- [ ] 03-01: LiveDataCache infrastructure — CachedFeed dataclass, LiveDataCache singleton, APScheduler AsyncIOScheduler wired in lifespan, TTL per feed type, fallback-to-None pattern [PARALLEL-SAFE with 03-02 after infrastructure]
- [ ] 03-02: GPR Index + ACLED ingestion — CSV download client for Caldara-Iacoviello GPR, ACLED REST API client (90-day rolling country conflict counts), both stored in LiveDataCache, wired into Chinese-origin and distributor-origin risk weighting [depends on 03-01]
- [ ] 03-03: IMF PortWatch + FRED freight ingestion — PortWatch GeoServices API client for LA/LB, NY/NJ, Savannah port wait-times wired as lead-time multiplier; FRED TSIFRGHT formalized with APScheduler replacing ad-hoc fetch; freshness timestamps on all four feeds [depends on 03-01]

### Phase 4: Benchmark Dashboard
**Goal**: An interviewer can open the Benchmark tab and see real numbers — graph-aware vs baseline A/B delta, Monte Carlo P10/P50/P90 bars, and an interactive Fiedler degradation card — all backed by a holdout scenario set
**Depends on**: Phase 2, Phase 3
**Requirements**: BENCH-01, BENCH-02, BENCH-03, BENCH-04, BENCH-05, BENCH-06, VIZ-01, VIZ-02, VIZ-03
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. `GET /api/v1/benchmark/summary` returns cost/ETA/CO2 deltas between graph-aware and baseline runs backed by a holdout scenario set — numbers are reproducible with a documented seed
  2. The Benchmark Dashboard tab displays before/after cards with percentage improvement numbers, a Monte Carlo P10/P50/P90 distribution chart, and at least one scenario where graph-aware routing is worse on one objective (demonstrating honest tradeoffs)
  3. The Fiedler degradation card shows λ₂ dropping as top-k distributors are removed, with each removed node labeled by name — "Removing DigiKey drops resilience by Y%"
  4. The Map page shows distributor nodes sized by betweenness centrality, colored by risk tier, with k-core single-source components highlighted in red
  5. `backend/seeds/run_benchmark.py` script runs reproducibly and populates optimization_runs with paired baseline/graph-aware rows for the same holdout BOMs
**Plans**: 4 plans

Plans:
- [ ] 04-01: optimization_runs table and benchmark data pipeline — SQLAlchemy ORM model, migration, graph_aware flag in optimize_bom(), run_benchmark.py seed script with holdout BOM set and fixed seed [depends on Phase 2 completion]
- [ ] 04-02: `GET /benchmark/summary` endpoint — A/B aggregation query over optimization_runs scalar columns, delta computation, cascade_risk_score column, benchmark.py API router [depends on 04-01]
- [ ] 04-03: Benchmark Dashboard frontend tab — before/after cards, Monte Carlo P10/P50/P90 Recharts area chart, Fiedler degradation curve (sequential node removal), honest tradeoff scenario display [depends on 04-02; PARALLEL-SAFE with 04-04]
- [ ] 04-04: Graph visualization on Map page — Deck.gl ScatterplotLayer sized by betweenness, risk-tier coloring, k-core red highlight for single-source components, cascade heatmap overlay [depends on Phase 2 graph API endpoints; PARALLEL-SAFE with 04-03]

### Phase 5: Prophet Demand Forecasting
**Goal**: The Prophet forecaster produces a 12-week demand horizon for the top 20 components and displays it on the Scheduler page alongside current stock levels
**Depends on**: Phase 1
**Requirements**: FORE-01, FORE-02, FORE-03
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. Importing prophet_forecaster.py raises no errors — all references to the deleted Material model are replaced with Component/DistributorOffer queries
  2. Running the forecast training script generates forecasts for the top 20 components by BOM frequency with a 12-week horizon and saves them to the DB
  3. The Scheduler page shows a forecast sparkline or trend indicator next to current stock level for each of the top 20 components — a user can see whether demand is trending up before placing an order
**Plans**: 3 plans

Plans:
- [ ] 05-01: Port prophet_forecaster.py — replace Material/PriceHistory imports with Component/DistributorOffer data source, implement BOM-frequency ranking to select top 20 components, validate no import errors
- [ ] 05-02: Forecast training pipeline — 12-week horizon forecast per top-20 component, output schema (component_id, forecast_date, predicted_demand, lower_bound, upper_bound), storage in SQLite, training script invocable via `python -m seeds.train_forecasts`
- [ ] 05-03: Scheduler page forecast display — API endpoint returning stored forecasts, frontend sparkline or trend badge per component card on SchedulerPage.tsx [depends on 05-02]

---

## Progress

**Execution Order:**
Phases 1 → 2 and 1 → 3 can overlap (Phase 3 only needs Phase 1). Phase 4 needs both 2 and 3. Phase 5 needs only Phase 1 and is fully independent of 2, 3, 4.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Codebase Hardening | 0/3 | Not started | - |
| 2. Graph ML Network Risk Engine | 0/4 | Not started | - |
| 3. Live Data Feeds | 0/3 | Not started | - |
| 4. Benchmark Dashboard | 0/4 | Not started | - |
| 5. Prophet Demand Forecasting | 0/3 | Not started | - |

---

## Architectural Constraints (Reference)

These are non-negotiable decisions documented here to inform plan execution.

- **Graph module pattern:** `app/graph/` mirrors `app/ml/` exactly — GraphState singleton, `get_graph_state()` / `set_graph_state()`, loaded in lifespan, accessed via local import inside `sourcing.py` to avoid circular imports
- **CP-SAT injection:** Additive integer-cent surcharges only — node weight on `y[did]` for betweenness/PageRank, edge surcharge on `q[key]` for single-source risk; surcharge ceiling = 15% of unit price to prevent centrality overriding genuine cost differences
- **Graph build:** Rebuild from SQLite at startup only, never per-request; store NetworkX DiGraph on `app.state.supply_graph`; centrality dict (92 entries) stored separately on `app.state.graph_risk_scores`
- **Live feeds:** All external API calls through FastAPI backend only; keys in `.env` never in frontend bundle; `CachedFeed` dataclass with `asyncio.Lock` and TTL; `APScheduler AsyncIOScheduler` shut down in lifespan cleanup after `yield`
- **Betweenness centrality:** Must use `bipartite.betweenness_centrality(G, dist_nodes)` weighted by inverse stock — topological-only betweenness is out of scope per REQUIREMENTS.md
- **Directed graph:** Use `nx.DiGraph` — edges run distributor → component, weighted by `1/max(stock,1)` to prevent division by zero
- **Benchmark holdout:** 20% of component/distributor combinations reserved before any strategy tuning or graph construction; `run_benchmark.py` uses fixed seed and documents it; benchmark claims always specify holdout vs. full-dataset
- **Demo resilience:** All live feed consumers check `CachedFeed.data is None` before use; optimizer returns valid result with static fallback scores when any feed is unavailable
