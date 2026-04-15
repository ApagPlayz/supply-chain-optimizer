# Project Research Summary

**Project:** Electronic Components Supply Chain Optimizer — Graph ML Extension
**Domain:** Graph ML supply chain risk platform (DS portfolio — Amazon SCOT, BCG, Google, UPS)
**Researched:** 2026-04-15
**Confidence:** HIGH

## Executive Summary

This project extends an existing FastAPI + React supply chain optimizer with a graph-based risk analysis layer. The recommended approach is a two-library strategy: NetworkX 3.4.x for graph construction, centrality analytics, community detection, and cascade simulation; PyG 2.7.0 (GAT/HeteroConv) for GNN node risk embeddings in a later phase. At 92 distributor nodes and 791 component nodes, this is a small graph — all NetworkX operations run in milliseconds and require zero GPU. The graph layer is justified not by computational necessity but by modeling power: multi-hop risk propagation and cascade failure logic require graph traversal that a flat pandas table cannot express. This framing must be stated explicitly in every interview conversation to preempt the "why not just use a DataFrame?" challenge.

The integration pattern is clean and low-risk. The existing CP-SAT MILP solver in `sourcing.py` already accepts additive integer-cent surcharges injected before `model.Minimize()` (the `_stockout_risk_premium_cents` pattern). Graph-derived risk scores slot directly into this same pattern: distributor-level betweenness centrality injects as a per-visit surcharge on `y[did]` terms; single-source edge risk injects as a per-offer surcharge on `q[key]` terms. The graph object is built once at startup, cached on `app.state`, and never rebuilt per-request. Live data feeds (FRED, IMF PortWatch, GPR Index, ACLED) are served via an in-memory TTL cache refreshed by APScheduler — no Redis required.

The top risks are analytical, not technical. The most dangerous failure mode is computing graph metrics without a structural argument for why those metrics apply to this specific bipartite graph topology — an interviewer at Amazon SCOT or BCG Gamma will ask exactly this. The second risk is benchmark contamination: comparing graph-aware routing against a baseline that was tuned on the same dataset. Both are solved by design choices before a line of code is written: use bipartite-appropriate algorithms (`bipartite.betweenness_centrality`, not the standard `betweenness_centrality`), and reserve a 20% BOM holdout before any strategy weight tuning begins.

---

## Key Findings

### Recommended Stack

Use NetworkX for all graph analytics and PyG for GNN training — these are complementary, not competing. The existing scikit-learn and FRED pipeline integrations are extended, not replaced. No new infra services (no Redis, no Neo4j, no graph database).

**Core technologies:**
- `networkx==3.4.2` — graph construction, centrality, community detection, cascade simulation — correct tool at this scale; lingua franca in supply chain graph research
- `python-louvain==0.16` — Louvain community detection — standard in SupplyGraph benchmark paper (arXiv 2408.14501)
- `torch-geometric==2.7.0` + `torch==2.5.1` — GAT/HeteroConv GNN training — confirmed best performer for supply chain risk (arXiv 2411.08550, Nov 2024)
- `fredapi==0.5.2` — FRED macro series (TSIFRGHT + 5 others already in pipeline) — already integrated; extend to live cache pattern
- `requests` / `httpx` (already in backend) — ACLED API, IMF PortWatch — both free with registration
- `apscheduler` — background feed refresh via `AsyncIOScheduler` — runs in same event loop as FastAPI, no thread pool needed

**Explicitly ruled out:** DGL (designed for giant graphs, adds complexity), Neo4j (overkill at 883 nodes), GraphSAGE (inductive learning irrelevant at fixed 92-node graph), Redis (< 10 cache keys, no distributed invalidation needed), Baltic Exchange / MarineTraffic / Portcast (paid commercial APIs, $200-2000/mo).

### Expected Features

See full feature landscape in `.planning/research/FEATURES.md`.

**Must have (table stakes — absence signals toy project):**
- Bipartite graph construction from `DistributorOffer` DB rows
- Degree centrality + betweenness centrality (bipartite-corrected, weighted by `1/stock`)
- Connected components analysis (reveals hidden single-source situations)
- HHI per component category (mirrors Fed Reserve Sourcing Risk Index methodology)
- Single-source ratio (% of BOM items with only one sourcing path)
- Basic graph statistics in a reportable benchmark table

**Should have (differentiators with defensible interview hooks):**
- Fiedler value (algebraic connectivity) + degradation curve under sequential node removal — quantifies how network splits when top-k distributors fail
- k-core decomposition — reveals the irreducible single-source core
- Monte Carlo cascade simulation (N=1000) — P10/P50/P90 BOM fulfillment distribution
- EVaR at 95th percentile disruption scenario — the number BCG reports to clients
- GAT node embeddings with attention weights — shows which components drive each distributor's risk score (interpretability is the value)
- A/B benchmark endpoint: graph-aware vs. baseline routing, mean cost delta with IQR across 50 BOMs

**Defer to v2+:**
- Temporal GNN (T-GCN, TGCRN) — requires time-series DB schema changes not currently in place
- Link prediction (shadow inventory) — high complexity, marginal portfolio return vs. cascade simulation
- Full port congestion live feed via paid API — use IMF PortWatch (free, weekly) as proxy
- Knowledge graph reasoning (neurosymbolic GNN) — active research area, high risk for a portfolio timeline

### Architecture Approach

The graph module is a new `backend/app/graph/` package that mirrors the existing `backend/app/ml/` pattern exactly. It is built once at startup in the `lifespan` context, stored on `app.state`, and accessed via module-level `get_graph_state()` with a local import inside `sourcing.py` (prevents circular imports — same pattern as `get_ml_state()`). Live feeds are served from a `LiveDataCache` dataclass on `app.state`, refreshed every 15 minutes by APScheduler.

**Major components:**
1. `app/graph/builder.py` — builds `nx.DiGraph` bipartite graph from DB at startup; ~500ms; never runs per-request
2. `app/graph/risk_scores.py` — computes `distributor_risk: Dict[int, float]` and `single_source_risk: Dict[Tuple, float]`; both consumed by `sourcing.py`
3. `app/graph/cascade.py` — SIR-style Monte Carlo simulation; outputs P10/P50/P90 fulfillment distribution
4. `app/graph/gnn_model.py` + `gnn_train.py` — PyG GAT HeteroConv; trained offline, served via `/api/v1/graph/risk`
5. `app/core/live_data_cache.py` — `CachedFeed` dataclass with TTL + `asyncio.Lock`; no Redis
6. `app/api/benchmark.py` — `GET /benchmark/summary` returning graph-aware vs. baseline delta statistics
7. `optimization_runs` SQLite table — `graph_aware` boolean flag; scalar columns pre-projected at INSERT for aggregation without JSON path queries

**Key integration point:** Graph risk scores inject into `sourcing.py` as additive integer-cent surcharges, capped at the existing 15-20% `RISK_PREMIUM_RATE` ceiling to prevent graph centrality from overriding genuine price differences.

### Critical Pitfalls

1. **Graph metrics without structural argument** — Calling `nx.betweenness_centrality(G)` on a bipartite distributor-component graph produces scores with no operational meaning unless edges are weighted and the bipartite projection is handled correctly. Use `networkx.algorithms.bipartite.betweenness_centrality(G, dist_nodes)` and weight edges by `1/stock`. For every metric exposed in the UI, prepare a two-sentence business translation ending in a dollar amount, headcount risk, or named procurement action.

2. **Benchmark contamination — same data for tuning and evaluation** — The VRP strategy weights (`consolidation_bonus`, `transport_penalty_scale`) were tuned on the full dataset. Comparing graph-aware vs. baseline on the same data inflates improvement claims. Reserve a 20% BOM holdout before any tuning. Report results as "median X% improvement, IQR Y–Z%" across 50 sampled BOMs — not a single headline number. Include at least one scenario where graph-aware routing is worse on a dimension (credibility).

3. **Live data feed that is actually stale cache** — Free tier API limits (some as low as 25 calls/month) drain during development; demos hit stale data. Mitigations: (a) display cache timestamp prominently ("Freight index as of 2026-04-14 09:00 UTC"), (b) implement `USE_LIVE_FEEDS=false` demo mode serving fixture JSON, (c) structure the demo to foreground FRED (no meaningful rate limits, already integrated) and treat other feeds as optional enhancement.

4. **Graph construction per-request** — Bipartite centrality for this graph takes 1-3 seconds. Building it per VRP request makes optimization unusably slow. Always precompute at startup and cache. Rule: graph rebuild only on server startup or explicit `/admin/reseed`.

5. **Directed vs. undirected graph confusion** — Supply chain flows are directed (`distributor → component`). Use `nx.DiGraph` from day one. An interviewer who notices a symmetric adjacency matrix for a directed flow will conclude the model was not thought through.

---

## Implications for Roadmap

Based on the feature dependency chain and pitfall risk profile, 4 phases are recommended.

### Phase 1: Graph Foundation and Metrics
**Rationale:** All downstream work (cascade simulation, GNN training, MILP integration) depends on a correctly constructed, validated graph. Build and validate the bipartite `DiGraph` first. Produces the interview-ready benchmark numbers immediately with low implementation risk.
**Delivers:** Validated graph on `app.state`; betweenness/degree/clustering centrality (bipartite-corrected, stock-weighted); HHI per category; single-source ratio; connected components; `GET /api/v1/graph/metrics` endpoint; `graph_analysis.ipynb` notebook with construction rationale.
**Addresses:** Table stakes features (FEATURES.md §Table Stakes), bipartite structural argument requirement (PITFALLS.md Pitfall 1), directed graph convention (PITFALLS.md Pitfall 8).
**Avoids:** Per-request graph build (precompute at startup from day one); unweighted centrality (weight edges by `1/stock` from the start).

### Phase 2: Resilience Analysis and MILP Integration
**Rationale:** Fiedler value and k-core depend on a validated graph from Phase 1. MILP injection is low-risk (additive surcharge pattern already proven) and produces the quantified "graph-aware vs. baseline" delta that is the core portfolio claim. The A/B benchmark table must be seeded before the GNN phase so comparisons use the holdout correctly.
**Delivers:** Fiedler degradation curve (λ₂ under sequential node removal); k-core decomposition; `graph_risk_cents` and `single_source_surcharge` injected into `sourcing.py`; `optimization_runs` table; `run_benchmark.py` CLI script; `GET /benchmark/summary` endpoint with cost/eta/co2 deltas.
**Addresses:** MILP integration pattern (ARCHITECTURE.md Q1); A/B benchmark design (FEATURES.md §Benchmark Output); benchmark contamination prevention (PITFALLS.md Pitfall 2 — holdout carved before this phase).
**Research flag:** Needs validation that graph surcharge cap (15-20%) is correctly calibrated — run a sensitivity check showing the solver still picks low-cost distributors when cost differences exceed the surcharge.

### Phase 3: Cascade Simulation and Live Feeds
**Rationale:** Monte Carlo simulation is the highest-differentiation deliverable for BCG/McKinsey audiences. It requires the validated graph and MILP integration from Phases 1-2 (uses ML lead time model for time-to-recovery). Live feeds are wired in this phase to feed macro stress edge re-weighting and geopolitical risk node features.
**Delivers:** SIR cascade model; Monte Carlo (N=1000); P10/P50/P90 BOM fulfillment distribution; EVaR at 95th percentile; targeted attack vs. random failure comparison; `LiveDataCache` + APScheduler background refresh; FRED, IMF PortWatch, GPR Index, and ACLED feeds behind TTL cache; `GET /api/v1/graph/simulate` endpoint; demo mode fixture fallback.
**Addresses:** Cascade/contagion features (FEATURES.md §Cascade); caching strategy (ARCHITECTURE.md Q2); stale-cache pitfall (PITFALLS.md Pitfall 3); API key security (PITFALLS.md Pitfall 4); live feed fallback (PITFALLS.md Pitfall 11).
**Research flag:** IMF PortWatch GeoServices API integration needs hands-on testing — free access is confirmed but Python client patterns are community-documented, not official.

### Phase 4: GNN Risk Embeddings
**Rationale:** GAT training requires a populated `optimization_runs` table (from Phase 2) for composite label construction and the validated graph from Phase 1 for `HeteroData` construction. Train offline; serve inference only. This is the highest complexity phase but lowest operational risk — it adds interpretability on top of already-working analytics.
**Delivers:** PyG `HeteroData` bipartite graph (distributor + component node types); 2-layer GAT HeteroConv model; composite risk score labels (centrality rank + cascade failure frequency + macro stress exposure); attention weight extraction showing which components drive each distributor's risk; `GET /api/v1/graph/risk` endpoint; GNN vs. logistic regression baseline comparison (delta, not absolute accuracy).
**Addresses:** GNN architecture decision (STACK.md Decision 3); GNN features (FEATURES.md §GNN-Based Features); reporting pattern (FEATURES.md §Anti-Features — always report delta vs. baseline, never raw accuracy).
**Research flag:** PyG `HeteroConv` with `add_self_loops=False` for bipartite graphs — verify this is still required in PyG 2.7.0 (was a known issue in 2.5.x). Confirm `torch-scatter` and `torch-sparse` wheel availability for the target Python/CUDA combination before starting.

### Phase Ordering Rationale

- **Foundation before injection:** The MILP surcharge in Phase 2 only produces credible results if the graph centrality values from Phase 1 are validated (bipartite-correct, weighted). Reversing this order risks injecting meaningless centrality scores into production optimization runs.
- **Benchmark before GNN:** The `optimization_runs` table needs populated rows (from Phase 2 benchmark runs) before Phase 4 can construct GNN training labels from composite scores. The holdout partition must also be defined before Phase 2 to prevent benchmark contamination.
- **Cascade before GNN:** Phase 3's cascade failure frequency per distributor is a key component of the GNN target label. Running Phase 3 first means Phase 4 training labels are richer and more defensible.
- **Live feeds in Phase 3, not Phase 1:** Feed integration adds operational complexity (TTL caching, fallback logic, API key management). Deferring to Phase 3 lets Phases 1-2 validate the graph and MILP integration on stable data before adding a moving external dependency.

### Research Flags

Phases needing deeper research during planning:
- **Phase 2:** Sensitivity analysis on graph surcharge cap — validate 15-20% ceiling is correct for this dataset's price distribution.
- **Phase 3:** IMF PortWatch API client integration pattern — free tier confirmed, but programmatic access patterns need hands-on validation.
- **Phase 4:** PyG 2.7.0 `HeteroConv` bipartite configuration — verify `add_self_loops=False` behavior and wheel availability for target environment.

Phases with standard patterns (skip research-phase):
- **Phase 1:** NetworkX bipartite graph construction and centrality are well-documented with confirmed patterns in both the official docs and the 2024 supply chain literature.
- **Phase 2:** MILP additive surcharge injection is a proven pattern already in `sourcing.py` (`_stockout_risk_premium_cents`). The `optimization_runs` SQLite table is straightforward.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | NetworkX + PyG confirmed via 2024-2025 papers and official releases; DGL/Neo4j exclusions confirmed; Freightos FBX free tier is MEDIUM (CSV export confirmed, API tier pricing unclear) |
| Features | HIGH | Feature list derived from arXiv 2411.08550 (Nov 2024) benchmark results and BCG/Amazon SCOT interview patterns; cascade simulation and HHI have strong literature backing |
| Architecture | HIGH | Integration pattern mirrors existing proven pattern in sourcing.py; APScheduler + FastAPI lifespan pattern is battle-tested; SQLite JSON column approach is intentionally simple |
| Pitfalls | HIGH | Pitfalls are grounded in specific interviewer challenges (BCG "so what?", Amazon "test/train split?") with concrete prevention steps; bipartite centrality correctness is well-documented |

**Overall confidence:** HIGH

### Gaps to Address

- **Freightos FBX API tier:** CSV export from the free terminal is confirmed; programmatic API access pricing is unclear. Mitigation: use FRED TSIFRGHT (already integrated, no rate limits) as the primary freight signal and treat FBX as optional enhancement only if the free CSV export is sufficient for the demo use case.
- **GNN training label construction:** The composite risk score (centrality + cascade frequency + macro stress) is conceptually sound but the exact weighting of the three components is a design choice not validated against held-out data. Frame this explicitly as a modeling decision with stated assumptions.
- **Bipartite graph connectivity:** The 92-distributor, 791-component graph may have isolated components (components with no offers in the DB after seeding). Fiedler value requires a connected graph — verify connectivity and document handling for disconnected subgraphs before Phase 2.

---

## Sources

### Primary (HIGH confidence)
- arXiv 2411.08550 (Nov 2024) — GNN architecture selection (GAT over GCN/GraphSAGE), supply chain task benchmarks
- arXiv 2408.14501 (Aug 2024) — SupplyGraph benchmark, Louvain community detection confirmation
- Scientific Reports 2024 (doi:10.1038/s41598-024-71345-y) — betweenness centrality + PageRank as cascade predictors in chip trade networks
- PyTorch Geometric GitHub releases — PyG 2.7.0 availability confirmed
- IMF PortWatch (portwatch.imf.org) — free public dataset, confirmed access
- ACLED API docs — free registration confirmed, no credit card required
- GPR Index (matteoiacoviello.com) — free CSV download, AER 2022 citation

### Secondary (MEDIUM confidence)
- Freightos FBX (fbx.freightos.com) — free terminal account confirmed; API tier pricing unclear
- FastAPI lifespan singleton pattern — community-documented, consistent with official FastAPI docs
- APScheduler + FastAPI integration — multiple community sources, battle-tested pattern

### Tertiary (needs validation)
- IMF PortWatch Python analytics (github.com/amanid/imf-portwatch-analytics) — community example, not official; verify GeoServices API access before relying on it

---
*Research completed: 2026-04-15*
*Ready for roadmap: yes*
