# Architecture Patterns: Graph ML + Live Data Feed Integration

**Project:** Electronic Components Supply Chain Optimizer
**Researched:** 2026-04-15
**Scope:** Integrating NetworkX/PyG graph risk module and live external data feeds
         into the existing FastAPI + SQLite + OR-Tools + scikit-learn backend.

---

## Current Architecture Baseline

The existing system has a clean three-layer pipeline per optimization request:

```
Request → sourcing.py (CP-SAT MILP) → routing.py (TSP) → solve.py (compose)
                ↑
         get_ml_state()  ←  startup lifespan loads joblib files
         (macro stress, lead time models)
```

Key integration points already established:
- `app.ml.get_ml_state()` / `set_ml_state()` — module-level singleton, loaded once at
  startup via the `lifespan` async context manager in `main.py`.
- `_stockout_risk_premium_cents()` in `sourcing.py` injects ML output as an additive
  integer-cent term into the CP-SAT objective. This is the proven injection pattern.
- `app.core.data_fetcher` / `app.core.clients.supplymaven_client` — async httpx clients
  called per-request. No persistent caching layer yet.

---

## Question 1: How Should Graph Risk Scores Feed Into the MILP Objective?

**Recommendation: Pre-computed node weight injected as an additive per-offer cost term
— same pattern as the existing `_stockout_risk_premium_cents` function.**

### Rationale

The CP-SAT model in `sourcing.py` requires integer coefficients. It cannot accept a
live Python object mid-solve. The correct integration point is before `model.Minimize()`,
where per-offer effective prices are assembled from component data.

Two options were evaluated:

**Option A — Node weight (distributor-level)**
A graph-derived "distributor concentration score" (e.g., betweenness centrality or
PageRank on the distributor-component bipartite graph) is precomputed and stored as a
float per `distributor_id`. At solve time it is looked up and scaled to an integer-cent
surcharge added to `y[did]` terms (the distributor-visit variables).

```
graph_risk_by_did: Dict[int, float]  # precomputed, stored on app.state

# In sourcing.py — added to transport_terms loop:
graph_risk_cents = int(round(
    graph_risk_by_did.get(did, 0.0) * base_price * GRAPH_RISK_RATE * PRICE_SCALE
))
transport_terms.append((est_transport_cents + graph_risk_cents) * y[did])
```

**Option B — Edge cost modifier (offer-level)**
A graph-derived score for each `(component_id, distributor_id)` pair is precomputed
and added to the per-unit `price_cents` for each `q[key]` term.

```
graph_edge_risk_by_key: Dict[Tuple[int,int], float]  # precomputed

price_cents = int(round(o.price_usd * PRICE_SCALE))
graph_surcharge = int(round(
    graph_edge_risk_by_key.get((b.component_id, o.distributor_id), 0.0)
    * o.price_usd * PRICE_SCALE
))
cost_terms.append((price_cents + graph_surcharge) * q[key])
```

**Use Option A (node weight on distributor visit) for graph centrality metrics.**
Betweenness centrality and PageRank are node properties of the supply graph — they
measure how critical a distributor is as a relay point for BOM coverage. These belong
on `y[did]` (distributor selection), not on individual offer quantities.

**Use Option B (edge cost on offers) for graph-derived single-source risk.** If the
graph reveals that a specific `(component, distributor)` pair is a single-supply-path
bottleneck — i.e., no alternative sourcing path exists in the graph — that is an edge
property and should modify the per-offer cost.

Both are additive integer-cent terms. They compose cleanly with the existing macro stress
surcharge (`risk_terms`) without touching the MILP model structure.

### Graph Metrics to Precompute

For 92 distributor nodes and 791 component nodes (8,731 edges), NetworkX runs in
< 1 second for all of the following:

| Metric | Graph Type | What It Captures | Inject As |
|--------|-----------|-----------------|-----------|
| Betweenness centrality (distributor) | Bipartite distributor-component | Distributor is a critical relay; removing it disconnects many components | Node weight on `y[did]` |
| Degree centrality (distributor) | Same bipartite | How many unique components a distributor covers | Node weight on `y[did]` |
| Single-source flag (edge) | Same bipartite | Component reachable from only one distributor | Edge surcharge on `q[key]` |
| Component reachability (node) | Directed risk propagation | How many components are affected if a distributor fails | Node weight on `y[did]` |

---

## Question 2: Caching Strategy for Live API Data

**Recommendation: In-memory TTL cache using a simple dataclass with `asyncio.Lock`,
refreshed by APScheduler `AsyncIOScheduler` on a fixed interval. No Redis. No
additional database table unless you need audit trails.**

### Why Not Redis

Redis adds an infra dependency (Docker service, connection pool, serialization) for a
problem that has < 10 data keys and < 1 MB of payload. For a portfolio project running
locally this is pure overhead. Redis becomes worthwhile when you need distributed cache
invalidation across multiple processes — not relevant here.

### Why Not SQLite TTL Table

A SQLite table with a `fetched_at` column and TTL logic works but has three
disadvantages for this use case:

1. Every request that misses the in-memory cache triggers a DB read + conditional async
   HTTP fetch, adding latency and disk I/O for data that changes hourly.
2. Schema migration required when adding new feed types.
3. Overly persistent — stale data survives server restarts, which can mask feed outages.

Use a SQLite TTL table only if you need cross-restart persistence of the last known
value (e.g., to avoid showing "N/A" on dashboard after a restart during a feed outage).

### Recommended Pattern

```python
# app/core/live_data_cache.py

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class CachedFeed:
    data: Optional[Dict[str, Any]]
    fetched_at: float          # time.monotonic()
    ttl_seconds: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_stale(self) -> bool:
        return time.monotonic() - self.fetched_at > self.ttl_seconds

# Singleton cache object — attached to app.state at startup
class LiveDataCache:
    freight_rates: CachedFeed      # TTL: 3600s (hourly)
    port_congestion: CachedFeed    # TTL: 900s  (15 min, matches SupplyMaven GDI)
    geopolitical_risk: CachedFeed  # TTL: 3600s (hourly, FRED series)
```

TTL values by data source:

| Feed | Update Frequency | Recommended TTL | Rationale |
|------|-----------------|-----------------|-----------|
| SupplyMaven GDI | 15 min | 900s | Provider's own update cadence |
| FRED macro series | Daily | 3600s | Fed data releases are daily at best |
| Port congestion | Hourly | 1800s | Portcast / SupplyMaven pro tier |
| Geopolitical risk | Hourly | 3600s | Geopolitical events move slowly |
| Commodity prices | Daily | 3600s | Alpha Vantage monthly for most |

### APScheduler Integration

```python
# In lifespan (main.py):
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(refresh_live_feeds, "interval", minutes=15)
scheduler.start()
app.state.live_cache = live_cache
app.state.scheduler = scheduler
# yield
scheduler.shutdown()
```

`AsyncIOScheduler` runs in the same event loop as FastAPI/uvicorn — no thread pool
needed. APScheduler 3.x is battle-tested with FastAPI and has no additional broker
dependency.

The background job calls the existing async httpx clients in `data_fetcher.py` and
`supplymaven_client.py`, updating the cache objects in place. Request handlers read
from the cache directly; they never trigger a live fetch themselves.

### Fallback Behavior

If a feed is unavailable (key not configured, API down), `CachedFeed.data` stays `None`
and all consumers check for `None` before using the value. This is the existing pattern
in `market_intelligence.py` — preserve it.

---

## Question 3: Graph Build and Persistence Strategy

**Recommendation: Rebuild the NetworkX graph from SQLite at startup. Store it on
`app.state.supply_graph`. Do not pickle to disk.**

### Why Not Pickle

- The graph is derived from `DistributorOffer` rows in SQLite. If the DB seed is
  re-run or offers are updated, a stale pickle silently diverges from the DB.
- Pickle files require version-pinned NetworkX. Any library upgrade can break
  deserialization silently.
- With 92 nodes + 791 nodes + 8,731 edges, rebuilding from SQLite takes < 500ms
  on startup — acceptable alongside the existing ML model load.

### Why Not an Edge List Table

NetworkX's `read_edgelist` format loses node/edge attributes. Storing a full
attributed edge list in SQLite requires a custom schema and is functionally identical
to just querying `DistributorOffer` at startup, which you already have.

### Build Pattern

```python
# app/graph/builder.py

import networkx as nx
from sqlalchemy.orm import Session
from app.models.component import DistributorOffer
from app.models.distributor import Distributor
from app.models.component import Component

def build_supply_graph(db: Session) -> nx.Graph:
    """
    Build a bipartite graph:
      - Distributor nodes: attrs = {lat, lng, tier, is_domestic, country}
      - Component nodes:   attrs = {category, risk_score, is_chinese_origin}
      - Edges (offer):     attrs = {price_usd, stock, moq}

    Runs once at startup. ~500ms for 92+791 nodes, 8731 edges.
    """
    G = nx.Graph()

    distributors = db.query(Distributor).all()
    for d in distributors:
        G.add_node(f"dist_{d.id}", type="distributor",
                   name=d.name, lat=d.latitude, lng=d.longitude,
                   tier=d.tier, is_domestic=d.is_domestic, country=d.country)

    components = db.query(Component).all()
    for c in components:
        G.add_node(f"comp_{c.id}", type="component",
                   category=c.category, risk_score=c.risk_score or 0.5,
                   is_chinese=c.manufacturer_country == "CN")

    offers = db.query(DistributorOffer).all()
    for o in offers:
        G.add_edge(f"dist_{o.distributor_id}", f"comp_{o.component_id}",
                   price=o.price, stock=o.stock or 0, moq=o.moq or 1)

    return G
```

### Centrality Scores — Precompute and Cache

Betweenness centrality for a bipartite graph of this size takes 1-3 seconds. Compute
once at startup and store the result dict separately from the graph object:

```python
# In lifespan, after graph build:
from networkx.algorithms import bipartite

dist_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "distributor"]
betweenness = bipartite.betweenness_centrality(G, dist_nodes)
degree_centrality = bipartite.degree_centrality(G, dist_nodes)

app.state.supply_graph = G
app.state.graph_risk_scores = {
    # distributor_id -> normalized risk score (0-1)
    int(n.split("_")[1]): betweenness[n]
    for n in dist_nodes
}
```

This dict (92 entries) is what `sourcing.py` looks up — not the full graph object.

### When to Rebuild

Rebuild the graph (and recompute centrality) only on:
- Server startup
- After `POST /admin/reseed` endpoint (if added)

Do not rebuild per-request. The supply graph reflects the static dataset, not live
pricing — it is structurally stable.

---

## Question 4: A/B Benchmark Comparison — Graph-Aware vs Baseline

**Recommendation: Single SQLite table `optimization_runs` with a JSON column for
full result payload and a boolean `graph_aware` flag. Add a `GET /benchmark/summary`
endpoint that queries this table and returns comparison statistics.**

### Table Schema

```sql
CREATE TABLE optimization_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    graph_aware INTEGER NOT NULL,  -- 0 = baseline, 1 = graph-aware
    strategy_id TEXT NOT NULL,     -- cheapest|fastest|greenest|balanced
    -- Key scalar metrics (indexed for aggregation queries)
    total_cost_usd    REAL,
    eta_p50_days      REAL,
    total_co2_kg      REAL,
    distributor_count INTEGER,
    -- Graph-specific fields (NULL for baseline runs)
    graph_risk_score_mean  REAL,
    graph_risk_score_max   REAL,
    -- Full payload for drill-down
    result_json TEXT  -- JSON-serialized RouteAlternative
);
```

Keep scalar columns for metrics you want to aggregate (AVG, STDEV) without parsing
JSON. Keep `result_json` for full drill-down without needing a separate response table.

SQLite stores JSON as TEXT. For a portfolio project this is fine — you are not doing
complex JSON path queries, just aggregating the scalar columns.

### Benchmark Endpoint

```python
# GET /api/v1/benchmark/summary

{
  "baseline": {
    "n": 42,
    "avg_cost_usd": 1240.50,
    "avg_eta_p50_days": 8.3,
    "avg_co2_kg": 12.1
  },
  "graph_aware": {
    "n": 42,
    "avg_cost_usd": 1198.20,
    "avg_eta_p50_days": 8.1,
    "avg_co2_kg": 11.4
  },
  "delta": {
    "cost_pct": -3.4,
    "eta_pct": -2.4,
    "co2_pct": -5.8
  }
}
```

This is what a hiring manager or McKinsey interviewer will click on — make it a
dedicated card on the Dashboard page.

### How to Populate the Table

Capture results inside `optimize_bom()` in `solve.py` before returning
`MultiRouteResponse`. Pass a `graph_aware: bool` flag into the orchestrator from the
API layer.

The existing pattern of passing `us_only` as a flag into `optimize_bom()` is the
precedent — add `graph_aware: bool = False` alongside it.

### A/B Comparison Run Script

For the portfolio demo, add a CLI script `backend/seeds/run_benchmark.py` that:
1. Loads a fixed set of BOM inputs (e.g., 10 representative carts from the DB).
2. Runs each BOM twice — once with `graph_aware=False`, once with `graph_aware=True`.
3. Writes both rows to `optimization_runs`.
4. Prints a Markdown table of deltas.

This script runs once to populate enough rows for the benchmark endpoint to show
meaningful statistics.

---

## Question 5: FastAPI + NetworkX Integration Patterns

**Established pattern: `app.state` singleton loaded in `lifespan`, accessed via
`Depends()` or direct `request.app.state` in route handlers.**

The existing codebase already follows this pattern for ML models (see `main.py`
lifespan and `app.ml.get_ml_state()`). The graph module mirrors this exactly.

### Module Layout

```
backend/app/
  graph/
    __init__.py        # get_graph_state(), set_graph_state(), GraphState dataclass
    builder.py         # build_supply_graph(db) -> nx.Graph
    risk_scores.py     # compute_distributor_risk(G) -> Dict[int, float]
                       # compute_single_source_edges(G) -> Dict[Tuple, float]
```

`GraphState` mirrors `MLState`:

```python
@dataclass
class GraphState:
    graph: nx.Graph
    distributor_risk: Dict[int, float]    # betweenness centrality, normalized
    single_source_risk: Dict[Tuple[int,int], float]  # (comp_id, dist_id) -> score
    built_at: datetime
```

`get_graph_state()` is called inside `sourcing.py` (local import, same pattern as
`get_ml_state()`) to fetch the precomputed risk dicts. If `GraphState` is `None`
(graph not yet built), surcharges default to 0 — no penalty applied.

### Dependency Injection Alternative

If you want type-safe injection into API routes (e.g., for the `/graph/risk` diagnostic
endpoint), use FastAPI `Depends`:

```python
def get_graph() -> GraphState:
    state = get_graph_state()
    if state is None:
        raise HTTPException(503, "Graph not loaded")
    return state

@router.get("/graph/risk")
def graph_risk_summary(graph: GraphState = Depends(get_graph)):
    ...
```

The optimization pipeline does not go through the router, so direct module-level access
(matching the existing `get_ml_state()` pattern) is cleaner there.

### NetworkX Version Note

NetworkX 3.x (current as of 2025) supports backend dispatch for GraphBLAS and
nx-cugraph accelerated backends — but these require separate installs and are not
needed at this graph size (92 + 791 nodes). Stick with standard `networkx` from
`requirements_minimal.txt`. The `nx-parallel` backend (uses joblib for parallel
algorithm execution) is also unnecessary at this scale.

---

## Component Boundary Summary

```
app/
  main.py
    lifespan:
      [existing] load ML models → set_ml_state()
      [new]      build_supply_graph(db) → compute_distributor_risk()
                 → set_graph_state(GraphState)
      [new]      start APScheduler → schedule live_feed_refresh every 15 min
                 → store LiveDataCache on app.state

  graph/                          ← NEW MODULE
    __init__.py     GraphState singleton (mirrors app/ml/__init__.py)
    builder.py      build_supply_graph(db: Session) -> nx.Graph
    risk_scores.py  compute_distributor_risk(G) -> Dict[int, float]
                    compute_single_source_edges(G) -> Dict[Tuple,float]

  core/
    live_data_cache.py             ← NEW: CachedFeed, LiveDataCache dataclasses
    [existing] data_fetcher.py     httpx FRED/Alpha Vantage async clients
    [existing] clients/
               supplymaven_client.py

  optimization/
    sourcing.py                    ← MODIFY: inject graph risk surcharges
                                     (additive int cents on y[did] and q[key])
    solve.py                       ← MODIFY: add graph_aware: bool flag,
                                     write to optimization_runs table

  api/
    [new] benchmark.py             GET /benchmark/summary — A/B comparison stats
    [new] graph.py                 GET /graph/risk — diagnostic endpoint

  models/
    [new] benchmark.py (SQLAlchemy) OptimizationRun ORM model
```

---

## Pitfalls to Avoid

### 1. Rebuilding the Graph Per Request
The bipartite centrality computation takes 1-3 seconds. Building it per VRP request
would make optimization unusably slow. Always precompute at startup and cache on
`app.state`.

### 2. Circular Import via `get_graph_state()` Inside `sourcing.py`
The existing code avoids circular imports by using a local import inside the function
body: `from app.ml import get_ml_state`. Apply the same pattern for
`from app.graph import get_graph_state`. Do not import at module level in `sourcing.py`.

### 3. Graph Risk Overpowering Price Signals
The existing `RISK_PREMIUM_RATE = 0.15` (15% max surcharge) was calibrated so the
risk surcharge cannot override large genuine cost differences. Use the same ceiling
for graph-derived surcharges. A graph centrality surcharge exceeding 20% of unit
price will cause the solver to always prefer low-centrality distributors regardless
of price — defeating the multi-objective purpose.

### 4. Missing Distributor IDs in Graph Risk Dict
If a distributor has no offers in the DB (possible after re-seeding a partial dataset),
it will not appear in the graph. All lookups into `distributor_risk` must use
`.get(did, 0.0)` — never direct index access.

### 5. APScheduler Not Shutting Down
APScheduler must be shut down in the lifespan cleanup block (after `yield`). If it
runs past server shutdown it will attempt to make HTTP calls with a closed event loop,
producing cryptic asyncio errors. The pattern: `scheduler.shutdown()` in the
lifespan's finally/post-yield block.

### 6. SQLite JSON Column Portability
For the benchmark table, `result_json` is stored as TEXT. Do not attempt SQLite JSON
path queries (`json_extract`) in aggregation queries — they are slow and brittle.
Pre-project the scalar columns you need at INSERT time.

---

## Sources

- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) — official docs, `app.state` singleton pattern
- [APScheduler 3.x Documentation](https://apscheduler.readthedocs.io/en/3.x/) — `AsyncIOScheduler`, interval jobs
- [NetworkX Bipartite Algorithms](https://networkx.org/documentation/stable/reference/algorithms/bipartite.html) — betweenness centrality on bipartite graphs
- [NetworkX Graph I/O](https://networkx.org/documentation/stable/reference/readwrite/edgelist.html) — edge list limitations (no node attributes)
- [SupplyGraph: Benchmark Dataset for Supply Chain GNNs](https://arxiv.org/abs/2401.15299) — evidence that graph-aware models outperform baselines 10-30% on supply chain tasks
- [nx-parallel](https://github.com/networkx/nx-parallel) — joblib-backed NetworkX backend (not needed at this graph scale)
- [FastAPI Singleton Pattern](https://medium.com/@hieutrantrung.it/using-fastapi-like-a-pro-with-singleton-and-dependency-injection-patterns-28de0a833a52) — `Depends()` vs `app.state` tradeoffs
- [Betweenness Centrality for Supply Chain Bottleneck Detection](https://graphable.ai/blog/betweenness-centrality-algorithm/) — practical centrality for identifying critical nodes
- [SupplyMaven API](https://supplymaven.com/developers) — GDI, port congestion, trade policy (already integrated in `market_intelligence.py`)
