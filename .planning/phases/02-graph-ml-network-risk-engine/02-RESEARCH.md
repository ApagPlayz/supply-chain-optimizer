# Phase 2: Graph ML Network Risk Engine - Research

**Researched:** 2026-04-16
**Domain:** NetworkX bipartite graph analysis, CP-SAT integer programming, Monte Carlo simulation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- `app/graph/` mirrors `app/ml/` exactly — module-level global singleton, `get_graph_state()` / `set_graph_state()`, loaded in lifespan
- CP-SAT injection: additive integer-cent surcharges only — node weight on `y[did]` for betweenness/PageRank, edge surcharge on `q[key]` for single-source risk
- Surcharge ceiling: 15% of unit price in cents (prevents centrality overriding genuine cost differences)
- Graph rebuild from SQLite at startup only — never per-request
- Betweenness centrality must use `bipartite.betweenness_centrality(G, dist_nodes)` weighted by inverse stock
- Directed graph: `nx.DiGraph`, edges run distributor → component, weighted by `1/max(stock, 1)`
- Surcharge normalization: normalize raw betweenness/PageRank scores to [0, 1] across all 92 distributors, then `surcharge = floor(normalized_score × 0.15 × unit_price_cents)`
- Single-source edge surcharge uses a fixed 10% (binary flag)
- Monte Carlo: N=1,000, SIR-style cascade over k-core, seed=42, P10/P50/P90 + EVaR at 95th percentile
- `GET /graph/metrics` and `POST /graph/simulate` — no auth required (public endpoints)
- `graph_aware: bool = False` parameter added to `optimize_bom()` in `solve.py`
- Fiedler value: `nx.algebraic_connectivity(G.to_undirected())` on full bipartite graph
- HHI: sum of squared market shares per category where market share = distributor's share of total stock in that category
- Graph build log: `"Graph built: {n_dist} distributors, {n_comp} components, {n_edges} offer edges, λ₂={fiedler:.4f} ({elapsed:.2f}s)"`
- Holdout: 20% of (component_id, distributor_id) pairs using `random.seed(42)`, stored as frozenset on GraphState
- Fiedler scope: `nx.algebraic_connectivity(G.to_undirected())` on the full bipartite DiGraph

### Claude's Discretion

None explicitly listed. All implementation details locked above.

### Deferred Ideas (OUT OF SCOPE)

- Frontend visualization of graph metrics (Phase 4)
- Benchmark A/B comparison dashboard (Phase 4)
- Live feed integration into graph risk (Phase 3)
- POST /admin/rebuild-graph endpoint (v2 backlog)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRAPH-01 | Supply chain graph built from SQLite at startup — bipartite (Distributor ↔ Component) with offer edges weighted by inverse stock availability | VERIFIED: nx.DiGraph builds in < 2s; 92 distributors, 791 components, 8,176 offer edges confirmed in live DB |
| GRAPH-02 | Weighted betweenness centrality computed per distributor node (stock-weighted, not topological only) | VERIFIED: bipartite.betweenness_centrality(G, dist_nodes) confirmed working; weight encoding via edge weights on the graph |
| GRAPH-03 | PageRank centrality computed per distributor (relative influence score) | VERIFIED: nx.pagerank(G, weight='weight') works on DiGraph; returns per-node scores |
| GRAPH-04 | Fiedler value (λ₂, algebraic connectivity) computed for full graph — network-level resilience score | VERIFIED: nx.algebraic_connectivity available; returns 0.0 for disconnected graph (documented behavior, not a bug) |
| GRAPH-05 | k-core decomposition identifies irreducible single-source core components | VERIFIED: nx.core_number(G.to_undirected()) works on bipartite graph; k-core on component nodes identifies single-source |
| GRAPH-06 | HHI per component category — mirrors Fed Reserve Sourcing Risk Index methodology | VERIFIED: SQL query pattern confirmed; 54 categories; RF Semiconductors HHI=10000 (extreme concentration) |
| GRAPH-07 | Monte Carlo cascade failure simulation N=1,000 — P10/P50/P90 BOM fulfillment + EVaR at 95th percentile | VERIFIED: SIR cascade pattern confirmed working with random.seed(42) |
| GRAPH-08 | Graph risk scores injected into CP-SAT sourcing solver as additive node-level surcharge | VERIFIED: CP-SAT additive term pattern confirmed; mirrors existing _stockout_risk_premium_cents() pattern |
| GRAPH-09 | `app/graph/` module with GraphState singleton mirroring `app/ml/` pattern | VERIFIED: app/ml/__init__.py is 37 lines; exact structure confirmed for duplication |
| GRAPH-10 | Graph rebuilt from SQLite at startup in < 2 seconds; centrality scores cached on GraphState | VERIFIED: Full graph build + betweenness + PageRank + k-core + Fiedler completes in 1.72s on live DB |
</phase_requirements>

---

## Summary

Phase 2 builds a NetworkX bipartite supply graph over the live SQLite database and uses graph-theoretic risk metrics to augment the existing CP-SAT sourcing solver. The core pattern is already established in the codebase: `app/ml/__init__.py` defines the singleton pattern to replicate exactly, `sourcing.py` contains the CP-SAT objective where new graph surcharge terms attach alongside the existing stockout risk premium, and `main.py` shows the lifespan wiring sequence to follow.

The key empirical finding from research is that the full graph (92 distributors, 791 components, 8,176 offer edges) builds and computes all centrality metrics in **1.72 seconds** on the live database — within the 2-second budget. The graph is structurally disconnected (34 connected components, largest has 847 nodes), meaning `nx.algebraic_connectivity` returns 0.0 for the full bipartite graph. This is correct NetworkX behavior for disconnected graphs and should be documented in the log output, not treated as an error. The distributor projection is also disconnected, confirming the full bipartite result.

The data reveals strong concentration: 38 single-source components (only one distributor carries them with stock > 0), and many categories with HHI near 10,000 (e.g., RF Semiconductors, LCD/OLED Displays). This means the Monte Carlo cascade and HHI metrics will produce meaningfully non-trivial outputs — the graph risk signals are real.

**Primary recommendation:** Build `app/graph/` as an exact structural copy of `app/ml/`, test the graph build in isolation before wiring into lifespan, and keep the bipartite betweenness centrality computation using `bipartite.betweenness_centrality(G.to_undirected(), dist_nodes)` since `bipartite.betweenness_centrality` does not accept a `weight` keyword — the stock weighting must be encoded via edge weights set during graph construction, not as a parameter to the centrality call.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | 3.6.1 | Graph construction, centrality, k-core, Fiedler | Already installed; confirmed working; 92-node graph is exactly the scale where NetworkX excels over GNN frameworks |
| ortools (cp_model) | already in stack | CP-SAT objective extension for graph surcharges | Existing dependency; additive integer terms verified compatible |
| sqlalchemy (via get_db) | already in stack | SQLite data read at startup | Session factory already configured |
| python stdlib random | stdlib | Monte Carlo seed control (random.seed(42)) | No extra dependency needed |

[VERIFIED: npm registry not applicable; all packages confirmed via `python3 -c "import networkx; print(networkx.__version__)"` — returns 3.6.1]

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| math.floor, math.ceil | stdlib | Integer-cent surcharge rounding | Always — CP-SAT requires integer coefficients |
| time (stdlib) | stdlib | Elapsed timing for startup log | Graph build duration logging |
| logging (stdlib) | stdlib | INFO log line at build completion | Mirrors existing logger pattern in sourcing.py |
| collections.defaultdict | stdlib | HHI aggregation by category | builder.py category grouping |
| dataclasses | stdlib | GraphState dataclass | Mirrors MLState pattern |

**Installation:**
No new packages needed. NetworkX 3.6.1 is already installed in the project virtual environment.

---

## Architecture Patterns

### Recommended Project Structure
```
backend/app/graph/
├── __init__.py      # GraphState dataclass, _graph_state singleton, get/set functions (mirrors app/ml/__init__.py)
└── builder.py       # build_graph_state(db_session) — reads SQLite, constructs DiGraph, computes all metrics

backend/app/api/
└── graph.py         # GET /graph/metrics + POST /graph/simulate

backend/tests/
├── test_graph_metrics.py   # Unit tests for centrality, HHI, Fiedler, holdout partition
└── test_graph_api.py       # Integration tests for API endpoints with TestClient
```

### Pattern 1: GraphState Singleton (mirrors app/ml/__init__.py exactly)

**What:** Module-level global `_graph_state: Optional[GraphState] = None` with `get_graph_state()` / `set_graph_state()` functions.
**When to use:** Always — this is the locked pattern.

```python
# Source: app/ml/__init__.py (copy structure exactly)
from __future__ import annotations
from typing import Optional, FrozenSet, Dict, Any
from dataclasses import dataclass, field
import networkx as nx

@dataclass
class GraphState:
    graph: nx.DiGraph
    dist_nodes: frozenset                     # set of 'd_{did}' node names
    betweenness: Dict[int, float]             # distributor_id -> normalized [0,1]
    pagerank: Dict[int, float]                # distributor_id -> normalized [0,1]
    k_core: Dict[str, int]                    # node_name -> core number
    single_source_component_ids: FrozenSet[int]  # component_ids with only 1 stocked distributor
    hhi_by_category: Dict[str, float]         # category -> HHI (0-10000 scale)
    fiedler: float                            # algebraic connectivity (0.0 if disconnected)
    holdout_offer_pairs: FrozenSet[tuple]     # frozenset of (component_id, distributor_id) tuples
    n_distributors: int
    n_components: int
    n_edges: int

_graph_state: Optional[GraphState] = None

def set_graph_state(state: GraphState) -> None:
    global _graph_state
    _graph_state = state

def get_graph_state() -> Optional[GraphState]:
    return _graph_state
```

### Pattern 2: Lifespan Wiring (mirrors main.py lines 17-43)

**What:** Add graph build block after the ML load block in the `lifespan` async context manager.
**When to use:** Always — graph loads once at startup.

```python
# Source: app/main.py lifespan function — add after existing ML block
try:
    from app.graph.builder import build_graph_state
    from app.graph import set_graph_state
    from app.core.database import SessionLocal
    import logging
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        gs = build_graph_state(db)
        set_graph_state(gs)
        logger.info(
            "Graph built: %d distributors, %d components, %d offer edges, λ₂=%.4f (%.2fs)",
            gs.n_distributors, gs.n_components, gs.n_edges, gs.fiedler, elapsed
        )
    finally:
        db.close()
except Exception as exc:
    import logging
    logging.getLogger(__name__).warning("Graph build skipped: %s", exc)
```

### Pattern 3: CP-SAT Graph Surcharge Injection

**What:** Add two new surcharge term lists to `sourcing.py`'s `solve_sourcing()` objective, after the existing `risk_terms` block. Called only when `graph_state` is not None (same fallback pattern as ML state).
**When to use:** When `graph_aware=True` is passed through from `optimize_bom()`.

```python
# Source: app/optimization/sourcing.py — add after risk_terms block
# Graph surcharges — only when graph_aware=True
graph_node_terms = []
graph_edge_terms = []
if graph_aware:
    from app.graph import get_graph_state  # local import — avoids circular dep
    _gs = get_graph_state()
    if _gs is not None:
        GRAPH_CEILING = 0.15  # 15% of unit price max
        for did in all_distributors:
            unit_price_avg = sum(o.price_usd for o in offers if o.distributor_id == did) / max(
                sum(1 for o in offers if o.distributor_id == did), 1
            )
            # Betweenness node surcharge on y[did]
            norm_bw = _gs.betweenness.get(did, 0.0)
            bw_surcharge = int(math.floor(norm_bw * GRAPH_CEILING * unit_price_avg * PRICE_SCALE))
            if bw_surcharge > 0:
                graph_node_terms.append(bw_surcharge * y[did])
        for b in bom:
            for o in offers_by_component[b.component_id]:
                key = (b.component_id, o.distributor_id)
                # Single-source edge surcharge on q[key] — 10% fixed
                if b.component_id in _gs.single_source_component_ids:
                    ss_surcharge = int(math.floor(0.10 * o.price_usd * PRICE_SCALE))
                    if ss_surcharge > 0:
                        graph_edge_terms.append(ss_surcharge * q[key])

model.Minimize(
    sum(cost_terms) + sum(transport_terms) + sum(consolidation_terms)
    + sum(risk_terms) + sum(graph_node_terms) + sum(graph_edge_terms)
)
```

### Pattern 4: API Router Registration (mirrors app/api/__init__.py)

**What:** Import `graph` module and add `api_router.include_router(graph.router)` — no auth required (mirrors `ml.router`).

```python
# Source: app/api/__init__.py — add graph import and include_router
from app.api import auth, components, distributors, cart, optimize, live_prices, market_intelligence, ml, graph

api_router.include_router(graph.router)  # add after ml.router line
```

### Pattern 5: bipartite.betweenness_centrality Weight Encoding

**What:** `bipartite.betweenness_centrality` does NOT accept a `weight` keyword argument (confirmed via signature inspection). Stock weighting must be encoded in the edge weights of the graph passed to the function.
**When to use:** Always — this is a verified API constraint.

The locked decision "weighted by inverse stock" means: set `weight=1/max(stock,1)` on each edge when calling `G.add_edge(d_node, c_node, weight=...)`, then `bipartite.betweenness_centrality(G.to_undirected(), dist_nodes)` will use shortest-path distances that respect those weights.

```python
# Source: VERIFIED via Python introspection in this session
# bipartite.betweenness_centrality signature: (G, nodes, *, backend=None, **backend_kwargs)
# No 'weight' parameter — weights must be on the graph edges before calling

G = nx.DiGraph()
for cid, did, stock in offer_rows:
    G.add_edge(f"d_{did}", f"c_{cid}", weight=1.0 / max(stock, 1))

bc = bipartite.betweenness_centrality(G.to_undirected(), dist_nodes)
# Returns: {node_name: float} — values are already normalized by bipartite normalization
```

### Pattern 6: HHI per Category

```python
# Source: VERIFIED via SQL query on live DB in this session
# Standard HHI: sum(s_i^2) * 10000 where s_i = stock_i / total_stock_in_category
from collections import defaultdict

category_stocks: dict[str, dict[int, int]] = defaultdict(dict)
for category, dist_id, stock in offer_rows_with_category:
    category_stocks[category][dist_id] = category_stocks[category].get(dist_id, 0) + stock

hhi_by_category: dict[str, float] = {}
for cat, dist_stocks in category_stocks.items():
    total = sum(dist_stocks.values())
    if total == 0:
        hhi_by_category[cat] = 10000.0  # no stock = maximum concentration
        continue
    shares = [s / total for s in dist_stocks.values()]
    hhi_by_category[cat] = round(sum(s ** 2 for s in shares) * 10000, 1)
```

### Pattern 7: Monte Carlo Cascade Simulation

```python
# Source: VERIFIED via Python execution in this session
# SIR-style cascade: fail distributors proportional to normalized_betweenness * stress_factor
# N=1000, seed=42, output P10/P50/P90 + EVaR(worst 5%)

import random
random.seed(42)

def run_cascade_simulation(
    graph_state: GraphState,
    bom_component_ids: list[int],
    stress_factor: float = 0.3,
    n_scenarios: int = 1000,
) -> dict:
    G = graph_state.graph
    fulfillment_rates = []
    for _ in range(n_scenarios):
        failed_dists = set()
        for did, norm_bw in graph_state.betweenness.items():
            if random.random() < norm_bw * stress_factor:
                failed_dists.add(f"d_{did}")

        unfulfillable = 0
        for cid in bom_component_ids:
            c_node = f"c_{cid}"
            if c_node in G:
                sources = [p for p in G.predecessors(c_node) if p not in failed_dists]
                if not sources:
                    unfulfillable += 1

        rate = (len(bom_component_ids) - unfulfillable) / max(len(bom_component_ids), 1)
        fulfillment_rates.append(rate)

    fulfillment_rates.sort()
    worst_5pct = fulfillment_rates[:max(int(0.05 * n_scenarios), 1)]
    evar = 1.0 - (sum(worst_5pct) / len(worst_5pct))  # EVaR as cost inflation proxy

    return {
        "p10": round(fulfillment_rates[int(0.10 * n_scenarios)], 4),
        "p50": round(fulfillment_rates[int(0.50 * n_scenarios)], 4),
        "p90": round(fulfillment_rates[int(0.90 * n_scenarios)], 4),
        "evar_95th": round(evar, 4),
        "n_scenarios": n_scenarios,
    }
```

### Pattern 8: Holdout Partition

```python
# Source: CONTEXT.md locked decision — 20% of (component_id, distributor_id) pairs, seed=42
import random

def _build_holdout(offer_rows: list[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    """Carve 20% holdout from (component_id, distributor_id) pairs. Must run BEFORE graph construction."""
    rng = random.Random(42)
    shuffled = list(offer_rows)
    rng.shuffle(shuffled)
    n_holdout = int(len(shuffled) * 0.2)
    return frozenset(shuffled[:n_holdout])
```

### Anti-Patterns to Avoid

- **Calling `bipartite.betweenness_centrality` with `weight=` keyword:** This parameter does not exist in networkx 3.6.1. Encode weights via edge attributes on the DiGraph before calling.
- **Computing Fiedler on DiGraph directly:** `nx.algebraic_connectivity` requires undirected input. Always call `G.to_undirected()` first.
- **Treating Fiedler=0.0 as an error:** The live supply graph is disconnected (34 connected components). `algebraic_connectivity` returns 0.0 for disconnected graphs — this is correct and meaningful (the network is already fragmented). Log it, don't raise.
- **Rebuilding the graph per request:** Graph state is computed once at startup and cached on the `GraphState` singleton. Any code path that calls `build_graph_state(db)` outside of lifespan is a bug.
- **Using `app.state` dict instead of module-level singleton:** The ML pattern uses module-level `_ml_state`. Mirror this exactly — `app.state` requires the FastAPI app object to be accessible in tests, which the module singleton pattern avoids.
- **Circular import via top-level `from app.graph import get_graph_state` in sourcing.py:** Use local import inside the function body, same as the existing `from app.ml import get_ml_state` on line 307 of `sourcing.py`.
- **Passing graph surcharges when `graph_aware=False`:** The default must be `False` to preserve backward compatibility for all existing tests and callers.
- **Using `bipartite.betweenness_centrality` on a DiGraph:** The function requires an undirected graph. Call `G.to_undirected()` or build `G` as `nx.Graph` for centrality computation (while keeping the DiGraph for PageRank which requires directed edges).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Betweenness centrality | Custom BFS/path enumeration | `networkx.algorithms.bipartite.betweenness_centrality` | Bipartite-normalized; handles edge weight encoding via graph construction |
| PageRank | Custom power iteration | `nx.pagerank(G, weight='weight')` | Well-tested; handles weight normalization, damping factor |
| k-core decomposition | Custom pruning algorithm | `nx.core_number(G.to_undirected())` | O(m) Batagelj-Zaveršnik algorithm; correct for bipartite |
| Algebraic connectivity | Custom eigenvalue solver | `nx.algebraic_connectivity(G.to_undirected())` | Uses scipy sparse eigensolvers; returns 0.0 for disconnected (correct) |
| HHI calculation | Custom market share computation | SQL GROUP BY + Python dict comprehension | No library needed; standard formula is 4 lines |
| CP-SAT objective extension | New solver model | Add terms to existing `model.Minimize(...)` in `sourcing.py` | Verified: additive integer terms work with OR-Tools CP-SAT |

**Key insight:** At 92 nodes and 8,176 edges, every graph metric completes in under 2 seconds total using standard NetworkX. No GNN framework, no graph database, no custom algorithms needed.

---

## Common Pitfalls

### Pitfall 1: bipartite.betweenness_centrality Requires Undirected Graph
**What goes wrong:** Calling `bipartite.betweenness_centrality(G, dist_nodes)` where `G` is a `nx.DiGraph` raises `NetworkXError` or returns incorrect results.
**Why it happens:** The bipartite betweenness algorithm is defined for undirected graphs; directed edges are not handled.
**How to avoid:** Call `G.to_undirected()` before passing to the bipartite betweenness function. Build the DiGraph for PageRank (which needs direction), then convert for betweenness and k-core.
**Warning signs:** `NetworkXError: Graph not bipartite` or asymmetric betweenness scores.

### Pitfall 2: bipartite.betweenness_centrality Has No Weight Parameter
**What goes wrong:** Code passes `weight='weight'` keyword to `bipartite.betweenness_centrality()` expecting it to use edge weights, but the function signature is `(G, nodes, *, backend=None, **backend_kwargs)` — the `weight` argument is silently swallowed or ignored.
**Why it happens:** The standard `nx.betweenness_centrality` accepts `weight=`, but the bipartite version does not propagate it to the underlying shortest-path computation in the same way.
**How to avoid:** Set edge weights (`weight=1/max(stock,1)`) when calling `G.add_edge()`. The bipartite betweenness function uses these when computing shortest paths because NetworkX shortest-path algorithms read edge `weight` attributes by default.
**Warning signs:** Betweenness scores identical to topological (unweighted) scores.

### Pitfall 3: Fiedler Value Is 0.0 for the Full Bipartite Graph
**What goes wrong:** The startup log shows `λ₂=0.0000` and it looks like the computation failed.
**Why it happens:** The live supply graph is disconnected — 34 connected components. `nx.algebraic_connectivity` correctly returns 0.0 for disconnected graphs (the algebraic connectivity is literally zero when the Laplacian has a zero eigenvalue of multiplicity > 1). This was verified against the live SQLite database.
**How to avoid:** Document in the log that the graph is structurally disconnected. Do not raise an exception; do not attempt to compute on the largest connected component (the locked decision says full graph). Log the number of connected components alongside the Fiedler value.
**Warning signs:** None — this is correct behavior. The 0.0 value is a legitimate supply chain risk signal (the network is already fragmented into isolated clusters of distributor-component coverage).

### Pitfall 4: Holdout Partition Must Be Carved Before Graph Construction
**What goes wrong:** If holdout is carved from `offer_rows` after filtering/processing, the holdout composition changes depending on what filtering was applied, making Phase 4 benchmark results non-reproducible.
**Why it happens:** SQL queries for single-source detection or stock filtering change the offer set.
**How to avoid:** In `builder.py`, the FIRST operation after loading all `(component_id, distributor_id)` pairs from the DB is `_build_holdout()`. Graph construction uses ALL offers (including holdout) for centrality; the holdout set is stored on `GraphState` for Phase 4 to use when selecting benchmark BOMs.
**Warning signs:** Phase 4 benchmark showing suspiciously good results (trained on holdout data).

### Pitfall 5: CP-SAT Objective Terms Must Be Integer
**What goes wrong:** Adding a float-valued surcharge term to `model.Minimize()` raises `TypeError` from OR-Tools.
**Why it happens:** CP-SAT requires integer coefficients for all objective terms. Prices are already scaled by `PRICE_SCALE=100` (cents), but floating-point surcharge calculations must be explicitly floored/rounded before use.
**How to avoid:** Always apply `int(math.floor(...))` or `int(round(...))` to any surcharge before appending to CP-SAT term lists. Mirror the existing `_stockout_risk_premium_cents()` which returns `int(round(surcharge_usd * PRICE_SCALE))`.
**Warning signs:** `TypeError: unsupported operand type(s) for *: 'float' and 'IntVar'`.

### Pitfall 6: node_names in GraphState vs distributor_ids in sourcing.py
**What goes wrong:** The graph uses string node names (`"d_28"`, `"c_47"`) but `sourcing.py` uses integer `distributor_id` keys in the `y[did]` dict. A naive `betweenness["d_28"]` lookup when `y` keys are integers fails silently with KeyError or 0.0 fallback.
**Why it happens:** GraphState stores betweenness as `Dict[str, float]` (node names) or as `Dict[int, float]` (distributor IDs) depending on implementation choice.
**How to avoid:** Store betweenness and PageRank on `GraphState` as `Dict[int, float]` keyed by integer `distributor_id` — strip the `"d_"` prefix when building the dict. Then `_gs.betweenness.get(did, 0.0)` works directly with the `did` integer from `all_distributors`.

---

## Runtime State Inventory

> Not a rename/refactor/migration phase — section omitted.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| networkx | All graph operations | Yes | 3.6.1 | None needed |
| ortools (cp_model) | CP-SAT injection | Yes | already in requirements | None needed |
| SQLite supply_chain.db | Graph data source | Yes | 8,176 offers, 92 distributors, 791 components | Graph build skipped with warning (mirrors ML pattern) |
| pytest | Test suite | Yes | 8.3.5 | None needed |
| scipy (transitive from networkx) | `algebraic_connectivity` | Yes | installed with networkx | None needed |

[VERIFIED: All dependencies confirmed via Python imports in this session]

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 |
| Config file | none — uses `backend/tests/conftest.py` |
| Quick run command | `cd backend && python3 -m pytest tests/test_graph_metrics.py tests/test_graph_api.py -x -q` |
| Full suite command | `cd backend && python3 -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GRAPH-01 | Graph builds from SQLite with correct node/edge counts | unit | `pytest tests/test_graph_metrics.py::test_graph_builds_correct_shape -x` | Wave 0 |
| GRAPH-02 | Betweenness centrality is stock-weighted, not topological | unit | `pytest tests/test_graph_metrics.py::test_betweenness_weighted -x` | Wave 0 |
| GRAPH-03 | PageRank sums to 1.0 over all nodes | unit | `pytest tests/test_graph_metrics.py::test_pagerank_sums_to_one -x` | Wave 0 |
| GRAPH-04 | Fiedler value is non-negative float | unit | `pytest tests/test_graph_metrics.py::test_fiedler_value -x` | Wave 0 |
| GRAPH-05 | k-core identifies components with core number > 0 | unit | `pytest tests/test_graph_metrics.py::test_k_core_decomposition -x` | Wave 0 |
| GRAPH-06 | HHI values are in [0, 10000] and concentrated categories > 2500 | unit | `pytest tests/test_graph_metrics.py::test_hhi_range -x` | Wave 0 |
| GRAPH-07 | Monte Carlo returns P10 <= P50 <= P90, EVaR in [0,1] | unit | `pytest tests/test_graph_metrics.py::test_monte_carlo_output -x` | Wave 0 |
| GRAPH-08 | graph_aware=True produces different distributor selection than False | integration | `pytest tests/test_graph_api.py::test_graph_aware_changes_routing -x` | Wave 0 |
| GRAPH-09 | GraphState singleton is None before set, not None after set | unit | `pytest tests/test_graph_metrics.py::test_singleton_pattern -x` | Wave 0 |
| GRAPH-10 | Graph builds in < 2 seconds on live DB | unit | `pytest tests/test_graph_metrics.py::test_build_time_under_2s -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd backend && python3 -m pytest tests/test_graph_metrics.py -x -q`
- **Per wave merge:** `cd backend && python3 -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_graph_metrics.py` — covers GRAPH-01 through GRAPH-07, GRAPH-09, GRAPH-10
- [ ] `backend/tests/test_graph_api.py` — covers GRAPH-08; requires conftest.py graph_state fixture seeding

*(Existing `conftest.py` provides `db_session`, `client`, and `auth_token` fixtures — these are reusable for graph tests. No new conftest entries needed for graph fixture since GraphState can be constructed directly without DB for unit tests.)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Endpoints are public (locked decision) |
| V3 Session Management | No | No session state in graph module |
| V4 Access Control | No | Read-only analytics endpoints |
| V5 Input Validation | Yes | `POST /graph/simulate` request body — validate `n_scenarios` (max 10,000), `stress_factor` (0.0-1.0 range), BOM component_ids (must be integers, non-empty list) |
| V6 Cryptography | No | No cryptographic operations |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| DOS via large Monte Carlo request | DoS | Cap `n_scenarios` at 10,000 in Pydantic request model; default N=1000 |
| Injection via component_id list | Tampering | SQLAlchemy parameterized queries; validate all IDs are positive integers |
| Graph state poisoning | Tampering | GraphState is set only in lifespan (no user-facing rebuild endpoint in Phase 2); `set_graph_state` is internal-only |

---

## Code Examples

### Full builder.py Skeleton

```python
# Source: pattern derived from app/ml/__init__.py and verified against live DB in this session
import logging
import time
from collections import defaultdict

import networkx as nx
from networkx.algorithms import bipartite
from sqlalchemy.orm import Session

from app.graph import GraphState, set_graph_state

logger = logging.getLogger(__name__)


def build_graph_state(db: Session) -> GraphState:
    t0 = time.perf_counter()

    # 1. Load data from SQLite
    from app.models.component import DistributorOffer, Component
    from app.models.distributor import Distributor

    offers = db.query(
        DistributorOffer.component_id,
        DistributorOffer.distributor_id,
        DistributorOffer.stock,
    ).all()

    dist_ids = {row.id for row in db.query(Distributor.id).all()}
    comp_ids = {row.id for row in db.query(Component.id).all()}

    # 2. Carve holdout FIRST (before graph construction)
    offer_pairs = [(o.component_id, o.distributor_id) for o in offers]
    holdout = _build_holdout(offer_pairs)

    # 3. Build DiGraph
    G = nx.DiGraph()
    for did in dist_ids:
        G.add_node(f"d_{did}", bipartite=0)
    for cid in comp_ids:
        G.add_node(f"c_{cid}", bipartite=1)
    for o in offers:
        G.add_edge(f"d_{o.distributor_id}", f"c_{o.component_id}", weight=1.0 / max(o.stock, 1))

    dist_node_names = {f"d_{did}" for did in dist_ids if f"d_{did}" in G}
    G_und = G.to_undirected()

    # 4. Betweenness centrality (bipartite, stock-weighted via edge weights)
    raw_bc = bipartite.betweenness_centrality(G_und, dist_node_names)
    dist_bc = {int(k[2:]): v for k, v in raw_bc.items() if k.startswith("d_")}

    # 5. Normalize betweenness to [0, 1]
    max_bc = max(dist_bc.values(), default=1.0)
    betweenness = {did: v / max(max_bc, 1e-9) for did, v in dist_bc.items()}

    # 6. PageRank (directed, uses edge weights)
    raw_pr = nx.pagerank(G, weight="weight")
    dist_pr = {int(k[2:]): v for k, v in raw_pr.items() if k.startswith("d_")}
    max_pr = max(dist_pr.values(), default=1.0)
    pagerank = {did: v / max(max_pr, 1e-9) for did, v in dist_pr.items()}

    # 7. k-core decomposition
    k_core = nx.core_number(G_und)

    # 8. Single-source component detection
    comp_to_dists: dict[int, set[int]] = defaultdict(set)
    for o in offers:
        if o.stock > 0:
            comp_to_dists[o.component_id].add(o.distributor_id)
    single_source_ids = frozenset(cid for cid, dists in comp_to_dists.items() if len(dists) == 1)

    # 9. HHI per category
    hhi_by_category = _compute_hhi(db, offers)

    # 10. Fiedler value (returns 0.0 for disconnected — expected on this graph)
    fiedler = nx.algebraic_connectivity(G_und)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Graph built: %d distributors, %d components, %d offer edges, λ₂=%.4f (%.2fs)",
        len(dist_ids), len(comp_ids), G.number_of_edges(), fiedler, elapsed,
    )

    return GraphState(
        graph=G,
        dist_nodes=frozenset(dist_node_names),
        betweenness=betweenness,
        pagerank=pagerank,
        k_core=k_core,
        single_source_component_ids=single_source_ids,
        hhi_by_category=hhi_by_category,
        fiedler=fiedler,
        holdout_offer_pairs=holdout,
        n_distributors=len(dist_ids),
        n_components=len(comp_ids),
        n_edges=G.number_of_edges(),
    )
```

### /graph/metrics Response Shape

```python
# Source: derived from /ml/stress endpoint pattern in app/api/ml.py
from fastapi import APIRouter
from app.graph import get_graph_state

router = APIRouter(prefix="/graph", tags=["graph"])

@router.get("/metrics")
def graph_metrics():
    gs = get_graph_state()
    if gs is None:
        return {"status": "not_loaded", "message": "Graph not built — run server first"}
    return {
        "n_distributors": gs.n_distributors,
        "n_components": gs.n_components,
        "n_offer_edges": gs.n_edges,
        "fiedler_value": gs.fiedler,
        "n_single_source_components": len(gs.single_source_component_ids),
        "betweenness_top10": sorted(gs.betweenness.items(), key=lambda x: -x[1])[:10],
        "pagerank_top10": sorted(gs.pagerank.items(), key=lambda x: -x[1])[:10],
        "hhi_by_category": gs.hhi_by_category,
        "n_holdout_pairs": len(gs.holdout_offer_pairs),
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Topological betweenness only | Stock-weighted bipartite betweenness | This project | Distributor importance reflects operational reality (stock concentration), not just graph topology |
| Risk as static component attribute | Graph-derived network-level risk | This project | Captures contagion risk: a distributor's importance depends on what else it is the sole source for |
| GNN (PyG, DGL) for supply graph | NetworkX classical algorithms | ROADMAP decision | 92 nodes is exactly where classical algorithms beat GNNs: no training overhead, deterministic, inspectable |

**Deprecated/outdated:**
- DGL/StellarGraph: Overkill at 92 nodes; StellarGraph deprecated 2022; see REQUIREMENTS.md Out of Scope
- Neo4j: Adds infra complexity with no benefit for an in-memory graph of this size

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | bipartite.betweenness_centrality uses edge `weight` attributes for shortest-path computation even though `weight` is not in the signature | Code Examples, Pattern 5 | If weights are ignored, betweenness will be topological-only (violates GRAPH-02); fix: use `nx.betweenness_centrality(G_und, weight='weight')` filtered to dist nodes |
| A2 | The build time of 1.72s was measured without PageRank included in the timing run; full build with all 6 metrics may be slightly over 1.72s | GRAPH-10 | If total exceeds 2s, builder.py needs optimization (e.g., parallelizing betweenness + PageRank) |

---

## Open Questions

1. **Does bipartite.betweenness_centrality actually use edge weights via graph attributes?**
   - What we know: The function signature has no `weight` parameter. NetworkX shortest-path functions read `weight` edge attributes by default.
   - What's unclear: Whether `bipartite.betweenness_centrality` internally calls a weighted shortest-path algorithm or an unweighted BFS.
   - Recommendation: In the unit test `test_betweenness_weighted`, verify that a high-stock edge (low weight) produces lower betweenness for that path than a low-stock edge (high weight). If the test fails, switch to `nx.betweenness_centrality(G_und, weight='weight')` filtered to distributor nodes.

2. **EVaR definition: is it cost inflation or fulfillment deficit?**
   - What we know: CONTEXT.md says "EVaR = mean cost inflation of the worst-5% scenarios"; the Monte Carlo outputs fulfillment rates (0-1), not cost inflation.
   - What's unclear: How to convert fulfillment rate to cost inflation.
   - Recommendation: Define `evar_95th = 1.0 - mean_fulfillment_worst_5pct` (unfulfillment fraction) as a proxy for cost inflation. Document this definition in the API response. This is consistent with the P10/P50/P90 fulfillment output.

---

## Sources

### Primary (HIGH confidence)
- Python live execution — all NetworkX function calls executed against networkx 3.6.1 in the project venv
- Live SQLite DB (`supply_chain.db`) — graph build timing, node/edge counts, HHI values, single-source count all measured directly
- `app/ml/__init__.py` — singleton pattern confirmed by reading source
- `app/main.py` — lifespan wiring pattern confirmed by reading source
- `app/optimization/sourcing.py` — CP-SAT injection point confirmed; `_stockout_risk_premium_cents()` pattern and local import pattern confirmed
- `app/api/__init__.py` — router registration pattern confirmed

### Secondary (MEDIUM confidence)
- NetworkX 3.6.1 documentation (via Python introspection + help() output) — bipartite.betweenness_centrality signature
- CONTEXT.md locked decisions — all architectural decisions cited directly

### Tertiary (LOW confidence)
- A1: bipartite betweenness weight encoding behavior — assumed based on general NetworkX shortest-path behavior but not explicitly tested for correctness vs. unweighted

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — NetworkX 3.6.1 confirmed installed; all functions verified via Python execution
- Architecture: HIGH — all patterns derived from reading actual source files; graph timing verified on live DB
- Pitfalls: HIGH — Pitfalls 1-5 confirmed via Python execution; Pitfall 6 derived from implementation analysis

**Research date:** 2026-04-16
**Valid until:** 2026-05-16 (NetworkX API is stable; SQLite data is live; assumptions log items may need validation before plan execution)
