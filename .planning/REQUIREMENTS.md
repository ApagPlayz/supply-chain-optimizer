# Requirements: Electronics Supply Chain Optimizer

**Defined:** 2026-04-15
**Core Value:** Demonstrate that ML-informed supply chain decisions (Graph ML network risk + live macro signals) produce quantifiably better outcomes than baseline optimization — with the numbers to prove it.

## v1 Requirements

### Codebase Hardening

- [ ] **HARD-01**: SECRET_KEY raises ValueError at startup if it matches the default dev value
- [ ] **HARD-02**: CORS allow_origins restricted to frontend domain via env var (not wildcard)
- [ ] **HARD-03**: DEBUG defaults to False; stack traces not exposed in production responses
- [ ] **HARD-04**: Live pricing and market intelligence endpoints require authentication (Depends get_current_user)
- [ ] **HARD-05**: Orphaned pre-pivot files (prophet_forecaster.py, forecast_tasks.py, data_pipeline.py) removed or ported to Component/DistributorOffer schema
- [ ] **HARD-06**: Demo login duplicate db.add bug fixed

### Graph ML — Network Risk Engine

- [ ] **GRAPH-01**: Supply chain graph built from SQLite at startup — bipartite (Distributor ↔ Component) with offer edges weighted by inverse stock availability
- [ ] **GRAPH-02**: Weighted betweenness centrality computed per distributor node (stock-weighted, not topological only)
- [ ] **GRAPH-03**: PageRank centrality computed per distributor (relative influence score)
- [ ] **GRAPH-04**: Fiedler value (λ₂, algebraic connectivity) computed for the full graph — network-level resilience score
- [ ] **GRAPH-05**: k-core decomposition identifies irreducible single-source core components
- [ ] **GRAPH-06**: HHI (Herfindahl-Hirschman Index) computed per component category — mirrors Fed Reserve Sourcing Risk Index methodology
- [ ] **GRAPH-07**: Monte Carlo cascade failure simulation (N=1,000 scenarios) — outputs P10/P50/P90 BOM fulfillment rates and EVaR cost inflation at 95th percentile
- [ ] **GRAPH-08**: Graph risk scores injected into CP-SAT sourcing solver as additive node-level surcharge (same pattern as existing stockout risk premium)
- [ ] **GRAPH-09**: `app/graph/` module with GraphState singleton mirroring `app/ml/` pattern
- [ ] **GRAPH-10**: Graph rebuilt from SQLite at startup in < 2 seconds; centrality scores cached on app.state

### Live Data Feeds

- [ ] **FEED-01**: GPR Index (Caldara-Iacoviello) ingested — monthly geopolitical risk score wired into Chinese-origin risk factor weighting
- [ ] **FEED-02**: ACLED conflict event count (free API, 90-day rolling window) per country wired into distributor origin risk
- [ ] **FEED-03**: IMF PortWatch congestion data ingested — weekly port wait-time signal for major US ports (LA/LB, NY/NJ, Savannah) wired as lead time modifier
- [ ] **FEED-04**: FRED TSIFRGHT freight transportation index refreshed on 15-min schedule (already partially integrated — formalize with APScheduler)
- [x] **FEED-05**: All live feed data cached in-memory with TTL; dashboard shows data freshness timestamp
- [x] **FEED-06**: Graceful degradation — optimizer falls back to static risk scores when any feed is unavailable; no 500 errors on API outage
- [x] **FEED-07**: All external API calls go through FastAPI backend; no API keys in frontend bundle or git

### Benchmark & Analytics

- [ ] **BENCH-01**: `optimization_runs` SQLite table stores every solver run with graph_aware boolean flag and pre-projected scalar columns (total_cost_usd, eta_p50_days, co2_kg, cascade_risk_score)
- [ ] **BENCH-02**: `GET /api/v1/benchmark/summary` endpoint returns A/B comparison: graph-aware vs baseline across all stored runs (% cost delta, % risk delta, % ETA delta)
- [ ] **BENCH-03**: Benchmark Dashboard tab in frontend — side-by-side before/after cards with % improvement numbers
- [ ] **BENCH-04**: Monte Carlo results displayed as distribution chart (P10/P50/P90 bars) not just point estimates
- [ ] **BENCH-05**: Fiedler value drop visualization — "removing distributor X drops network resilience by Y%" interactive card
- [ ] **BENCH-06**: Holdout scenario set (20% of component/distributor combinations reserved) used for all benchmark claims — no benchmark on training data

### Graph Visualization

- [ ] **VIZ-01**: Network graph visualization on Map page — distributor nodes sized by betweenness centrality, colored by risk tier
- [ ] **VIZ-02**: k-core components highlighted — components with no alternative source shown in red
- [ ] **VIZ-03**: Cascade simulation animation or heatmap showing which distributors failing triggers BOM fulfillment collapse

### Prophet Demand Forecasting (Resurrection)

- [ ] **FORE-01**: prophet_forecaster.py ported to use Component/DistributorOffer as data source (replaces deleted Material model)
- [ ] **FORE-02**: Demand forecast for top 20 components by BOM frequency — 12-week horizon
- [ ] **FORE-03**: Forecast output displayed on Scheduler page alongside current stock levels

## v2 Requirements

### Temporal GNN

- **TGNN-01**: Add timestamps to DistributorOffer rows to enable temporal graph analysis (SC-TGN architecture)
- **TGNN-02**: Temporal GNN predicts offer-level risk from graph embeddings (requires PyTorch training pipeline)

### MLOps

- **MLOPS-01**: APScheduler job for automated model retraining on new offer data
- **MLOPS-02**: Model versioning with joblib + metadata tracking (trained_at, RMSE, feature_cols)
- **MLOPS-03**: POST /admin/rebuild-graph endpoint (auth-gated) to trigger graph rebuild after offer sync

### External Data Expansion

- **EXT-01**: SupplyGraph (CIOL 2024) benchmark dataset integrated for GNN validation
- **EXT-02**: ETO ChipExplorer semiconductor supply chain network data ingested
- **EXT-03**: Commodity prices (copper, tin, rare earths) via FRED as upstream cost signal

## Out of Scope

| Feature | Reason |
|---------|--------|
| Neo4j / graph database | Overkill for 92-node in-memory graph; adds infra complexity with no portfolio signal |
| DGL (Deep Graph Library) | Targets million-node distributed training; adds backend deps for zero benefit at this scale |
| StellarGraph | Deprecated 2022 |
| MarineTraffic / Portcast (paid) | No paid API budget; IMF PortWatch is free and sufficient |
| Baltic Exchange API | Paid membership required; FRED TSIFRGHT is free equivalent |
| Real-time order execution / ERP integration | Portfolio project, not a production procurement system |
| Mobile app | Web-only sufficient for portfolio purposes |
| Multi-tenant SSO / RBAC | Adds complexity without DS portfolio signal |
| Betweenness centrality without stock weighting | Topological-only betweenness is meaningless on a bipartite supply graph — always weight by inverse stock availability |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| HARD-01 through HARD-06 | Phase 1 | Pending |
| GRAPH-01 through GRAPH-10 | Phase 2 | Pending |
| FEED-01 through FEED-07 | Phase 3 | Pending |
| BENCH-01 through BENCH-06 | Phase 4 | Pending |
| VIZ-01 through VIZ-03 | Phase 4 | Pending |
| FORE-01 through FORE-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 36 total
- Mapped to phases: 36
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-15*
*Last updated: 2026-04-15 after initial definition*
