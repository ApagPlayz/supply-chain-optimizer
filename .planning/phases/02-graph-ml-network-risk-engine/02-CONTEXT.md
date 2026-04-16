---
phase: 02-graph-ml-network-risk-engine
created: 2026-04-16
mode: auto
---

# Phase 2 Context: Graph ML Network Risk Engine

**Phase Goal:** A GraphState singleton loads at startup, computes all risk scores in < 2 s, and injects them as additive CP-SAT surcharges that produce measurably different routing decisions.

**Auto mode:** All decisions below were selected automatically. No user interaction required.

---

## Prior Decisions (Locked from Phase 1 / ROADMAP)

- `app/graph/` mirrors `app/ml/` exactly — module-level global singleton, `get_graph_state()` / `set_graph_state()`, loaded in lifespan
- CP-SAT injection: additive integer-cent surcharges only — node weight on `y[did]` for betweenness/PageRank, edge surcharge on `q[key]` for single-source risk
- Surcharge ceiling: 15% of unit price in cents (prevents centrality overriding genuine cost differences)
- Graph rebuild from SQLite at startup only — never per-request
- Betweenness centrality must use `bipartite.betweenness_centrality(G, dist_nodes)` weighted by inverse stock
- Directed graph: `nx.DiGraph`, edges run distributor → component, weighted by `1/max(stock, 1)`

---

## Decisions

### 1. GraphState singleton pattern
**[auto] Mirrors `app/ml/__init__.py` exactly — module-level `_graph_state: Optional[GraphState] = None` with `get_graph_state()` / `set_graph_state()`.**

The ML module pattern is the established convention in this codebase. Avoids `app.state` dictionary which requires the FastAPI app object in tests. The `get_graph_state()` function is called via local import inside `sourcing.py` to avoid circular imports — same pattern as `get_ml_state()`.

### 2. Surcharge normalization
**[auto] Normalize raw betweenness/PageRank scores to [0, 1] range across all 92 distributors, then surcharge = `floor(normalized_score × 0.15 × unit_price_cents)`.**

This keeps the surcharge proportional to the component price (15% ceiling) and avoids the surcharge overwhelming cheap passive components. PageRank and betweenness are normalized separately. Single-source edge surcharge uses a fixed 10% (binary flag — either single source or not).

### 3. Monte Carlo propagation model
**[auto] SIR-style cascade propagation over k-core subgraph — N=1,000 scenarios, fixed seed=42 for reproducibility.**

Each scenario: randomly fail top-betweenness distributors (failure probability = normalized_betweenness × stress_factor). Propagate over k-core adjacency. Count which BOM components become unfulfillable. Output P10/P50/P90 fulfillment rates and EVaR = mean cost inflation of the worst-5% scenarios.

### 4. API endpoint authentication
**[auto] `GET /graph/metrics` and `POST /graph/simulate` — no auth required (public endpoints).**

Mirrors the `/ml/stress` and `/ml/model-comparison` endpoints which are also public. These are read-only analytics that interviewers will call directly to inspect the system — requiring auth would add friction with no security benefit.

### 5. `graph_aware` flag wiring
**[auto] Add `graph_aware: bool = False` parameter to `optimize_bom()` in `solve.py`. When True, call `get_graph_state()` and apply surcharges in `solve_sourcing()` via the existing risk premium pattern.**

The surcharge injection point is inside `sourcing.py`'s CP-SAT model objective, same location as the existing `_stockout_risk_premium_cents()` call. The `optimize.py` API router passes `graph_aware` from the request body. Default is `False` to preserve backward compatibility.

### 6. Fiedler value computation scope
**[auto] Compute algebraic connectivity on the full bipartite DiGraph (distributor + component nodes).**

`nx.algebraic_connectivity(G.to_undirected())` on the full graph gives the most meaningful resilience score — a low Fiedler value indicates the graph is near-disconnected and a single distributor removal would fragment supply. Computing on distributor-only projection would lose the component-level concentration signal.

### 7. HHI per category
**[auto] HHI computed as sum of squared market shares per component category, where market share = distributor's share of total stock in that category.**

Mirrors Federal Reserve's Sourcing Risk Index methodology. A category with HHI > 2500 is "highly concentrated" (1 or 2 dominant distributors). Store per-category HHI dict on GraphState. Include in `/graph/metrics` response.

### 8. Graph build logging
**[auto] Log at INFO level: `"Graph built: {n_dist} distributors, {n_comp} components, {n_edges} offer edges, λ₂={fiedler:.4f} ({elapsed:.2f}s)"`.**

This satisfies the ROADMAP success criterion that "Server startup log shows graph build completed in under 2 seconds with node/edge counts". The log line is the interview-visible proof point.

### 9. Holdout partition
**[auto] Carve holdout before graph construction — reserve 20% of (component_id, distributor_id) offer pairs using `random.seed(42)`. Store holdout set as a frozenset on GraphState. Benchmark seed scripts use only non-holdout offers for strategy tuning.**

The ROADMAP architectural constraints explicitly flag this as a pre-Phase-4 requirement. Establish the partition in Phase 2 builder.py so it's available when Phase 4 runs benchmarks.

---

## Codebase Patterns to Follow

- **Singleton pattern:** `app/ml/__init__.py` — copy structure exactly for `app/graph/__init__.py`
- **Lifespan wiring:** `app/main.py` lines 15–44 — add graph build block after ML load block, same try/except/warning pattern
- **API router registration:** `app/api/__init__.py` — add `graph.py` router with prefix `/graph`
- **Surcharge injection:** `app/optimization/sourcing.py` — find `_stockout_risk_premium_cents()` call and add graph surcharge in the same objective block
- **Test pattern:** `backend/tests/` — use `TestClient` with SQLite in-memory DB; seed test data directly

---

## Out of Scope for Phase 2

- Frontend visualization of graph metrics (Phase 4)
- Benchmark A/B comparison dashboard (Phase 4)
- Live feed integration into graph risk (Phase 3)
- POST /admin/rebuild-graph endpoint (v2 backlog)

---

## Files to Create

| File | Purpose |
|------|---------|
| `backend/app/graph/__init__.py` | GraphState singleton, get/set functions |
| `backend/app/graph/builder.py` | Build DiGraph from SQLite, compute all metrics, return GraphState |
| `backend/app/api/graph.py` | GET /graph/metrics + POST /graph/simulate endpoints |
| `backend/tests/test_graph_metrics.py` | Unit tests for centrality, HHI, Fiedler |
| `backend/tests/test_graph_api.py` | Integration tests for graph endpoints |

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/main.py` | Add graph build block in lifespan |
| `backend/app/api/__init__.py` | Register graph router |
| `backend/app/optimization/sourcing.py` | Add graph surcharge to CP-SAT objective |
| `backend/app/optimization/solve.py` | Add `graph_aware` flag to `optimize_bom()` |
| `backend/app/api/optimize.py` | Pass `graph_aware` from request body |
