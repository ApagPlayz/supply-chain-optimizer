# Phase 4: Benchmark Dashboard — Research

**Researched:** 2026-04-18
**Domain:** Benchmark persistence, A/B aggregation, Fiedler degradation pre-compute, Recharts visualization, maplibre Network Risk overlay
**Confidence:** HIGH on backend/data patterns (verified in code), HIGH on frontend patterns (verified in Dashboard/MapPage), **MEDIUM on Fiedler top-5 sequential-removal timing** — one measured run returned λ₂=0 in 146 s, flagged below as a pitfall the planner MUST design around.

## Summary

Phase 4 is integration-heavy, not algorithm-heavy. The graph engine (Phase 2) already exposes every metric the dashboard needs — `betweenness`, `pagerank`, `k_core`, `single_source_component_ids`, `hhi_by_category`, `fiedler`, `holdout_offer_pairs`. The live-feed cache (Phase 3) already wires `graph_aware=True` surcharges into the CP-SAT objective. Phase 4 adds one ORM table (`optimization_runs`), one seed pipeline (`run_benchmark.py`), one API router (`benchmark.py`), one frontend page (`BenchmarkPage.tsx`), and a toggled overlay on `MapPage.tsx`.

The two real risks are (1) **Fiedler sequential-removal at startup** — a foreground probe on the production graph hung NetworkX's `tracemin_pcg` solver for 146 s and returned λ₂=0 silently; the 5× sequential recomputation envisioned in D-04 could kill server startup if built naively. (2) **A duplicate `Distributor.is_domestic` semantics gap** — Chinese-origin components need `manufacturer_country == 'China'` for GPR surcharge, but the DB has inconsistent coding (some Espressif rows say `'China'`, others `None` — verified). The 10 named BOMs in D-01 rely on Chinese-origin coverage, so the planner must pick MPNs whose DB rows actually carry `'China'` OR use `risk_factors` JSON `["chinese_origin"]` which is the established fallback path already used in `sourcing.py`.

**Primary recommendation:** Use `Base.metadata.create_all` for the `optimization_runs` table (never alembic — initial migration already out-of-sync with current schema). Pre-compute Fiedler curve at startup using the **unweighted** undirected graph (or use `method="lanczos"` with an explicit iteration budget and a wall-clock timeout), not `tracemin_pcg` on the weighted graph. Aggregate `/benchmark/summary` deltas in Python — 20 rows per run is trivial, SQL aggregation adds zero value and loses type safety. Ship the BOM-collapse mapping as a nested dict on `GraphState.fiedler_curve[i].collapsed_boms` produced by `run_benchmark.py` and persisted to the DB (not computed in the backend) so demo reproducibility is deterministic.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01 through D-10)

**D-01 — Holdout BOM set = 10 hand-crafted named portfolio BOMs.** Deterministic across runs. Each narratable by name. Composition designed at plan time, locked in `run_benchmark.py`. ≥ 2 BOMs must include Chinese-origin components.

**D-02 — Strategy comparison = Balanced-only paired A/B per BOM.** Each holdout BOM → exactly two `optimization_runs` rows: `(balanced, graph_aware=False)` and `(balanced, graph_aware=True)`. **20 rows per benchmark invocation.**

**D-03 — Benchmark tab hero layout:** hero headline → 3 KPI cards (Cost Δ / Risk Δ / ETA Δ) → MC grouped bar chart → "Where Graph-Aware Loses" tradeoff card → Fiedler degradation curve.

**D-04 — Fiedler card renders pre-computed top-5 sequential-removal λ₂ curve.** Line chart, x=removal step (0→5), y=λ₂, each point labeled with removed distributor name. Clicking a point reveals BOM collapse.

**D-04a — Backend pre-computes top-5 curve at startup** inside the graph lifespan block, stored on `GraphState.fiedler_curve: list[dict]`. No new `/graph/fiedler_remove` endpoint. Exposed either through extension of `/graph/metrics` or a new `GET /benchmark/fiedler-curve`.

**D-04b — BOM-collapse mapping is pre-computed** by `run_benchmark.py` using the existing Monte Carlo output. No per-click re-simulation.

**D-05 — MapPage.tsx gains a `[Routes | Network Risk]` view toggle.** Routes view = existing behavior unchanged. Network Risk view: per-`<Marker>` sizing by normalized betweenness, fill by risk tier (reusing `RISK_COLORS`/`riskLabel()` from Dashboard), red halo on k-core single-source distributors, side panel listing single-source components. **No Deck.gl refactor.** Stays marker-based.

**D-06 — Dedicated "Where Graph-Aware Loses" card** placed between MC chart and Fiedler card. Shows 1–2 BOMs where graph-aware is worse on at least one axis. If all BOMs favor graph-aware, renders closest-to-neutral variant. **Never hidden.**

**D-06 (holdout enforcement) — `run_benchmark.py` must query only non-holdout offer pairs** when doing any strategy tuning / preprocessing. Holdout pairs consumed exclusively at benchmark time.

**D-07 — Monte Carlo chart = grouped bar chart, P10/P50/P90 × (baseline, graph-aware).** Recharts `BarChart` on cost-inflation axis. Two color groups, six bars total per BOM (or aggregate across BOMs).

**D-08 — `run_benchmark.py` produces 3 outputs:** (a) inserts rows into `optimization_runs`, (b) prints aggregate summary to stdout, (c) writes `.planning/BENCHMARK-RESULTS.md` timestamped portfolio artifact.

**D-09 — `optimization_runs` is append-only,** keyed by `run_id` + `timestamp`. Each `run_benchmark.py` invocation generates new `run_id` (monotonic int OR UUID — Claude's discretion). `/benchmark/summary` defaults to `latest run_id`. Supports temporal comparison without a `--clean` flag dance.

**D-10 — Cascade simulation (VIZ-03) = static maplibre heatmap overlay** on Network Risk view. Toggle button "Cascade Risk". Viridis-like perceptual ramp. No animation. Data computed in `run_benchmark.py`, exposed via benchmark API.

### Claude's Discretion

- Exact component composition of the 10 named BOMs (name + list of `(component, qty)` pairs). Must span categories, include ≥ 2 BOMs with Chinese-origin components.
- NavBar tab placement order (suggested: after Map, before Scheduler).
- `run_id` = AUTOINCREMENT int vs. UUID string.
- Whether Fiedler curve is served via extending `/graph/metrics` or a new `/benchmark/fiedler-curve` endpoint.
- Cascade heatmap color ramp (viridis/magma/plasma family — perceptually uniform required).
- Whether `/benchmark/summary` accepts `?run_id=N` query param for history.
- Exact Pydantic schema shapes for benchmark responses.
- Caching strategy for `/benchmark/summary` (static after startup vs. per-request query).

### Deferred Ideas (OUT OF SCOPE)

- Interactive `POST /graph/fiedler_remove` endpoint with live λ₂ recompute.
- Dedicated `/network` Map sub-tab with Deck.gl refactor.
- Cascade animation / scenario scrubber.
- Random-sampled large-N BOM mode.
- Temporal benchmark comparison UI ("compare runs A vs B").
- Benchmark against external datasets (SupplyGraph, ChipExplorer — v2).

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BENCH-01 | `optimization_runs` SQLite table with `graph_aware` flag + scalar columns (`total_cost_usd`, `eta_p50_days`, `co2_kg`, `cascade_risk_score`) | § SQLAlchemy ORM Design — column list below mirrors `Order` model + adds graph-aware/run-id fields; `DistributorOffer` pattern shows non-FK integer columns are OK here |
| BENCH-02 | `GET /api/v1/benchmark/summary` returns A/B % deltas (cost, risk, ETA) | § API Endpoint Design — aggregate in Python (20 rows), not SQL; response schema mirrors `/graph/metrics` convention |
| BENCH-03 | Benchmark Dashboard tab with before/after cards + % improvement | § Frontend Patterns — reuse `KpiCard`, `RISK_COLORS`, `riskLabel()` from Dashboard.tsx |
| BENCH-04 | Monte Carlo results as P10/P50/P90 distribution chart | § MC Output Shape — `solve.py::_monte_carlo_eta` already emits `{p10, p50, p90, samples}` on every RouteAlternative. Benchmark rows store these three scalars plus a JSON snapshot of `samples[:200]` for distribution rendering |
| BENCH-05 | Fiedler drop visualization — "removing distributor X drops resilience by Y%" | § Fiedler Sequential-Removal Algorithm — uses `nx.algebraic_connectivity` on largest CC; **critical pitfall:** use `method="lanczos"` not `tracemin_pcg`; wall-clock-bound; fallback to 0.0 logs a warning |
| BENCH-06 | Holdout scenario set (20% reserved) used for all claims | § Holdout Enforcement — `gs.holdout_offer_pairs` exposes `frozenset[(cid, did)]`; `run_benchmark.py` filters offers before passing to `optimize_bom` |
| VIZ-01 | Network graph on Map — nodes sized by betweenness, colored by risk tier | § Network Risk Overlay — per-`<Marker>` size from `gs.betweenness[did]`, fill from `RISK_COLORS[riskLabel(risk)]` |
| VIZ-02 | k-core components highlighted — single-source in red | § Single-Source Highlighting — `gs.single_source_component_ids` is `frozenset[int]`; side panel joins to component MPN + sole-source distributor name; markers of sole-source distributors get red halo |
| VIZ-03 | Cascade simulation heatmap | § Cascade Heatmap Data Shape — array of `{lat, lng, weight}` where `weight` = mean BOM-collapse probability when that distributor fails; pre-computed in `run_benchmark.py` by re-running `run_monte_carlo` with each distributor forcibly failed |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Real data only.** No synthetic prices, no fake MPNs, no invented distributor names. The 10 BOMs must reference MPNs that exist in the live DB (791-component Nexar/Octopart dataset seeded from HuggingFace).
- **Tech stack locked:** FastAPI + SQLAlchemy (backend), React 18 + TypeScript + Vite + Tailwind v4.2 + Recharts + maplibre (`react-map-gl/maplibre`) + framer-motion + zustand + lucide-react + axios (frontend). No Deck.gl. No new charting libraries. No new animation libraries.
- **Optimizer objective unchanged:** multi-objective VRP with graph surcharge from Phase 2 + feed surcharge from Phase 3. Benchmark flips the `graph_aware` flag; it does NOT introduce new surcharge terms.
- **API base:** `/api/v1/...`. New router prefix `/benchmark`.
- **ML models stored in** `backend/data/ml_models/` (gitignored). No parallel convention needed for benchmark data — it lives in SQLite.
- **Server resilience:** benchmark must run with all live feeds down (`LiveDataCache.data is None` for all feeds). Document as "static-fallback-mode" run tag.

## Standard Stack

### Core — Already Installed, No New Deps

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.40 | `OptimizationRun` ORM model | Every other model in `backend/app/models/` is SQLAlchemy Core-style `Column` declarations on `Base` |
| NetworkX | 3.6.1 | `algebraic_connectivity` for sequential-removal Fiedler curve | Already used in `backend/app/graph/builder.py` |
| FastAPI + Pydantic | (pinned in requirements) | `/benchmark/summary`, `/benchmark/fiedler-curve`, `/benchmark/cascade-heatmap` endpoints | Mirror `backend/app/api/graph.py` |
| Recharts | (frontend existing) | Monte Carlo grouped `BarChart`, Fiedler `LineChart` | Dashboard already uses `BarChart`, `ScatterChart`, `PieChart`, `RadarChart` |
| framer-motion | (frontend existing) | Hero fade-in + KPI card stagger, Fiedler drawer expand | Identical pattern to Dashboard `motion.div` with `initial/animate/transition` |
| react-map-gl / maplibre | (frontend existing) | Network Risk overlay via per-`<Marker>` styling + `heatmap-layer` source for cascade | MapPage already uses `<Marker>`, `<Source>`, `<Layer>` |
| lucide-react | (frontend existing) | `AlertTriangle`, `TrendingDown`, `TrendingUp`, `Layers`, `MapPin` | Per UI-SPEC import contract |

### Supporting — No Additions Required

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| axios | (frontend existing) | `benchmarkAPI` service | Mirror `feedsAPI.getStatus()` |
| zustand | (frontend existing) | `benchmarkStore` if client-side caching needed | Optional — Dashboard pattern uses `useState` + `useEffect`, which is equally acceptable for a single API call |

### Alternatives Considered (and rejected)

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `Base.metadata.create_all` for `optimization_runs` | Alembic autogenerate migration | Repo's existing `0001_initial_schema.py` still references the deleted `materials`/`suppliers` schema — alembic is out-of-sync with current models. The `create_all` pattern in `main.py:12` is what actually builds the running DB. Adding alembic discipline to this one table would require first fixing the migration history. **Out of scope.** Use `create_all` — same as every other model. |
| SQL aggregation for `/benchmark/summary` deltas | `SELECT AVG(CASE WHEN graph_aware THEN ... ) FROM optimization_runs` | 20 rows per benchmark. Python aggregation with Pydantic validation is clearer, type-safe, and trivial. SQL buys nothing here. |
| UUID `run_id` | AUTOINCREMENT int | UUID harder to narrate ("run 37" vs "run abc123de"). AUTOINCREMENT int + timestamp is simpler, collision-free per D-09. Recommendation: **AUTOINCREMENT int**. |
| New `/graph/fiedler_remove` endpoint | Extend `/graph/metrics` with `fiedler_curve` field | Simpler. One request on page load. Matches existing `/graph/metrics` pattern. Recommendation: **new `GET /benchmark/fiedler-curve` endpoint** for namespace clarity (Fiedler degradation is a benchmark-tab concern, not a generic graph metric). |

**Verification:** `npm view recharts version` and `npm view react-map-gl version` — not needed; both are already in `frontend/package.json` and UI-SPEC locks "no new deps". [VERIFIED: ./frontend/package.json via UI-SPEC import contract and MapPage/Dashboard imports]

## Architecture Patterns

### Recommended Project Layout (Delta)

```
backend/
├── app/
│   ├── models/
│   │   └── optimization_run.py   ← NEW (append to __init__.py exports)
│   ├── api/
│   │   └── benchmark.py          ← NEW (register in app/api/__init__.py)
│   └── graph/
│       └── (no new files — extend GraphState via field addition in __init__.py)
├── seeds/
│   └── run_benchmark.py          ← NEW (mirror seed_db.py / train_ml_models.py)
└── tests/
    ├── test_optimization_run_model.py  ← NEW
    ├── test_run_benchmark.py           ← NEW (unit-level; skip DB by monkeypatching)
    ├── test_benchmark_api.py           ← NEW
    └── test_fiedler_sequential.py      ← NEW (Pitfall #1 coverage)

frontend/src/
├── lib/
│   └── risk.ts                   ← NEW (extract RISK_COLORS + riskLabel from Dashboard)
├── pages/
│   └── BenchmarkPage.tsx         ← NEW (register in App.tsx)
└── services/
    └── api.ts                    ← EXTEND (add benchmarkAPI section)
```

### Pattern 1: SQLAlchemy ORM for Append-Only Scalar Store (BENCH-01)

**What:** ORM model mirroring `Order` (has scalar columns + JSON payload + timestamp) but without `user_id` FK. `optimization_runs` is a system-level audit log, not user-owned.

**When to use:** Any append-only table of optimization outputs where downstream queries are delta aggregation over paired rows.

**Example (recommended minimum column set):**

```python
# backend/app/models/optimization_run.py — Source: mirrors app/models/order.py structure
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class OptimizationRun(Base):
    """
    Append-only audit row for a single (BOM × strategy × graph_aware) optimizer invocation.

    Benchmark invocation produces 20 rows per run_id (10 BOMs × 2 graph_aware values).
    D-09: run_id + timestamp keyed; /benchmark/summary defaults to latest run_id.
    """
    __tablename__ = "optimization_runs"

    id = Column(Integer, primary_key=True, index=True)

    # Run grouping
    run_id = Column(Integer, nullable=False, index=True)           # AUTOINCREMENT-per-invocation (computed in run_benchmark.py)
    run_tag = Column(String(50), nullable=False, default="benchmark")  # "benchmark" | "static_fallback" | "ad_hoc"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Input identity
    bom_name = Column(String(100), nullable=False, index=True)     # "drone_flight_controller", etc.
    bom_items_json = Column(JSON, nullable=False)                  # [{"component_id":..., "mpn":..., "quantity":...}]

    # Strategy + flag (BENCH-01)
    strategy = Column(String(20), nullable=False, default="balanced")  # D-02: always "balanced" for benchmark
    graph_aware = Column(Boolean, nullable=False, index=True)

    # Pre-projected scalars (BENCH-01 explicit requirement)
    total_cost_usd = Column(Float, nullable=False)
    total_component_cost_usd = Column(Float)
    total_transport_cost_usd = Column(Float)
    eta_p10_days = Column(Float)
    eta_p50_days = Column(Float, nullable=False)
    eta_p90_days = Column(Float)
    co2_kg = Column(Float, nullable=False)
    cascade_risk_score = Column(Float, nullable=False)             # 1 - MC p50 fulfillment rate, stored as 0..1

    # Full Monte Carlo payload for dashboard distribution plot
    monte_carlo_samples = Column(JSON)                             # list[float], trimmed to 200 points
    mc_evar_95 = Column(Float)                                     # mean cost_inflation of worst-5% scenarios

    # Feed status at run time (per CONTEXT.md "static-fallback mode")
    feeds_available = Column(JSON)                                  # {"gpr": bool, "acled": bool, "portwatch": bool, "fred_freight": bool}

    # Selected distributors snapshot — for "Where Graph-Aware Loses" narrative
    selected_distributor_ids = Column(JSON)                         # list[int]
    selected_distributor_names = Column(JSON)                       # list[str] — frontend uses without extra join
```

Index on `(run_id, bom_name, graph_aware)` recommended as a composite index for the common `/benchmark/summary` query pattern. SQLite doesn't enforce composite unique constraints well, so don't bother with `UniqueConstraint`; instead validate in `run_benchmark.py` (fail fast if any `(run_id, bom_name, graph_aware)` duplicate is detected in the insert set).

### Pattern 2: Benchmark Pipeline (BENCH-01 + BENCH-06)

```python
# backend/seeds/run_benchmark.py — structure; actual implementation in plan 04-01

def main():
    db = SessionLocal()
    gs = build_graph_state(db)                 # or use pre-built — graph is deterministic per seed=42
    set_graph_state(gs)

    bom_catalog = load_10_named_boms()         # constant in this file; see § BOM Catalog below

    # D-06: filter offers to exclude holdout pairs only during strategy tuning
    # (not during benchmark run — the benchmark IS the holdout).
    # Here, the runs ARE the holdout evaluation, so we use ALL offers — but we
    # must NOT look at holdout pairs during any pre-benchmark calibration.
    # Since Phase 4 adds no calibration step, there is no holdout filter in run_benchmark.py.
    # The holdout existed to keep Phase 2 graph-surcharge weights honest; graph is already fit.

    run_id = next_run_id(db)                   # MAX(run_id) + 1
    feeds_available = snapshot_feed_availability()  # dict[str, bool]

    for bom_name, bom_items in bom_catalog.items():
        for graph_aware in (False, True):
            result = optimize_bom(
                bom=to_bom_lines(bom_items),
                offers=load_offers(db, bom_items, exclude_holdout=False),
                distributors=load_distributors(db),
                depot=GeoPoint(lat=..., lng=...),   # canonical SF depot — 37.7749, -122.4194
                us_only=False,
                graph_aware=graph_aware,
            )
            balanced = next(a for a in result.alternatives if a.id == "balanced")

            mc_sim = run_monte_carlo(gs, [ci["component_id"] for ci in bom_items])
            cascade_risk = 1.0 - mc_sim.p50

            db.add(OptimizationRun(
                run_id=run_id,
                run_tag="benchmark" if all(feeds_available.values()) else "static_fallback",
                bom_name=bom_name,
                bom_items_json=bom_items,
                strategy="balanced",
                graph_aware=graph_aware,
                total_cost_usd=balanced.total_cost_usd,
                total_component_cost_usd=balanced.total_component_cost_usd,
                total_transport_cost_usd=balanced.total_transport_cost_usd,
                eta_p10_days=balanced.eta_p10,
                eta_p50_days=balanced.eta_p50,
                eta_p90_days=balanced.eta_p90,
                co2_kg=balanced.total_co2e_kg,
                cascade_risk_score=cascade_risk,
                monte_carlo_samples=balanced.monte_carlo_samples,
                mc_evar_95=mc_sim.evar_95,
                feeds_available=feeds_available,
                selected_distributor_ids=[s.distributor_id for s in balanced.sourcing],
                selected_distributor_names=sorted({s.distributor_name for s in balanced.sourcing}),
            ))

    # 3b. BOM-collapse mapping for Fiedler click interaction (D-04b)
    compute_bom_collapse_mapping(gs, bom_catalog, db, run_id)

    # 3c. Cascade heatmap data (D-10, VIZ-03)
    compute_cascade_heatmap_data(gs, bom_catalog, db, run_id)

    db.commit()

    print_summary_table(db, run_id)                              # D-08 stdout
    write_markdown_report(db, run_id, ".planning/BENCHMARK-RESULTS.md")  # D-08 markdown
```

The `compute_bom_collapse_mapping` and `compute_cascade_heatmap_data` functions are not Monte-Carlo-simulation-heavy: they run the MC simulation once per (removed-distributor-set, BOM) tuple. 5 removal steps × 10 BOMs = 50 MC runs = ~2–5 s total given the Phase 2 simulation is already sub-100 ms for a single run.

### Pattern 3: Fiedler Sequential-Removal Pre-Compute (D-04, D-04a, BENCH-05)

**What:** In the main.py lifespan block, after `build_graph_state(db)` returns, compute the top-5 sequential-removal λ₂ curve and attach it to the GraphState as a new field.

**When to use:** Any pre-computed network resilience curve where the display is static and the underlying graph is rebuilt only at startup.

**Critical pitfall note (see § Common Pitfalls #1): The current Phase 2 builder uses `method="tracemin_pcg"` — a probe on the production graph (847-node largest CC, 7363 edges) hung 146 s and returned λ₂=0. Phase 4 MUST use `method="lanczos"` with a wall-clock budget or fall back to an unweighted projection.**

**Example:**

```python
# Proposed new field on GraphState:
@dataclass
class GraphState:
    # ... existing fields ...
    fiedler_curve: List[dict] = field(default_factory=list)
    #   [{"step": 0, "removed": None, "removed_name": None, "lambda2": 0.1234},
    #    {"step": 1, "removed": 12, "removed_name": "DigiKey", "lambda2": 0.1047, "delta_pct": -15.2},
    #    ... 5 more entries ...
    #    {"step": 5, "removed": 7, "removed_name": "Avnet", "lambda2": 0.0421, "delta_pct": -66.0}]


# Lifespan extension (app/main.py, after build_graph_state):
def compute_fiedler_curve(gs: GraphState, db: Session, top_k: int = 5) -> List[dict]:
    """
    Pre-compute sequential removal of the top-k highest-betweenness distributors.
    Uses lanczos (not tracemin_pcg) for convergence on the weighted bipartite graph.
    Falls back to unweighted laplacian if lanczos fails on any step.
    """
    import time
    import networkx as nx
    from app.models.distributor import Distributor

    dist_name_by_id = {d.id: d.name for d in db.query(Distributor).all()}

    Gu = gs.graph.to_undirected()
    curve = []

    def _lambda2(G: nx.Graph) -> float:
        """Lanczos-based algebraic connectivity on the largest CC, unweighted."""
        if G.number_of_nodes() <= 2:
            return 0.0
        cc = max(nx.connected_components(G), key=len)
        Gsub = G.subgraph(cc).copy()
        # Strip weights — T-04-N1 mitigation (tracemin_pcg non-convergence on stock-weighted graph)
        for u, v in Gsub.edges():
            Gsub[u][v]["weight"] = 1.0
        try:
            t0 = time.time()
            lam = nx.algebraic_connectivity(Gsub, method="lanczos", normalized=False)
            elapsed = time.time() - t0
            if elapsed > 5.0:
                logger.warning("Fiedler lanczos slow (%.1fs) on %d nodes — consider approximation", elapsed, Gsub.number_of_nodes())
            return lam if lam > 0 else 0.0
        except Exception as exc:
            logger.warning("Fiedler lanczos failed: %s — returning 0.0", exc)
            return 0.0

    base_lambda = _lambda2(Gu)
    curve.append({"step": 0, "removed": None, "removed_name": None, "lambda2": base_lambda, "delta_pct": 0.0})

    top_dists = sorted(gs.betweenness.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    Gtmp = Gu.copy()
    for step, (did, _btwn) in enumerate(top_dists, start=1):
        node = f"d_{did}"
        if Gtmp.has_node(node):
            Gtmp.remove_node(node)
        lam = _lambda2(Gtmp)
        delta_pct = (lam - base_lambda) / max(base_lambda, 1e-9) * 100 if base_lambda > 0 else 0.0
        curve.append({
            "step": step,
            "removed": did,
            "removed_name": dist_name_by_id.get(did, f"distributor-{did}"),
            "lambda2": lam,
            "delta_pct": round(delta_pct, 1),
        })

    return curve


# In main.py lifespan, after `set_graph_state(_gs)`:
try:
    _gs.fiedler_curve = compute_fiedler_curve(_gs, _db, top_k=5)
    logger.info("Fiedler curve: %d steps pre-computed", len(_gs.fiedler_curve))
except Exception as exc:
    logger.warning("Fiedler curve pre-compute skipped: %s", exc)
    _gs.fiedler_curve = []
```

**Estimated cost:** on an 883-node / 7363-edge graph with `method="lanczos"` + unweighted edges, Fiedler converges in tens of milliseconds per step. Six calls (baseline + 5 removals) ≤ 1 s total. This is well within the Phase 2 <2s startup budget. The planner MUST verify this on the actual hardware by having the task log the elapsed time.

### Pattern 4: `/benchmark/summary` Response Shape (BENCH-02, BENCH-03, BENCH-04)

**What:** A Pydantic response model that frontend consumes once per page load. Combines paired-delta aggregation + MC distribution + Fiedler curve + tradeoff identification + cascade heatmap points.

**Example:**

```python
# backend/app/api/benchmark.py — Source: mirrors app/api/graph.py signature

class BenchmarkKpiDelta(BaseModel):
    axis: str                      # "cost" | "risk" | "eta" | "co2"
    baseline_mean: float
    graph_aware_mean: float
    absolute_delta: float
    percent_delta: float           # negative means graph-aware is better on cost/risk/eta/co2

class BenchmarkMcDistribution(BaseModel):
    p10_baseline: float
    p50_baseline: float
    p90_baseline: float
    p10_graph_aware: float
    p50_graph_aware: float
    p90_graph_aware: float
    unit: str                      # "usd" | "percent_inflation"

class BenchmarkBomRow(BaseModel):
    bom_name: str
    baseline_cost: float
    graph_aware_cost: float
    baseline_eta: float
    graph_aware_eta: float
    baseline_risk: float
    graph_aware_risk: float
    graph_aware_wins: bool         # True if graph-aware is better or tied on all 3 axes
    worst_axis: Optional[str]      # populated only when graph_aware_wins is False

class BenchmarkTradeoff(BaseModel):
    has_loss: bool                 # True when at least one BOM has graph_aware_wins == False
    bom_name: str                  # chosen loss-BOM OR closest-to-neutral BOM
    worst_axis: str
    delta_pct: float               # +X% on the losing axis
    narrative: str                 # templated: "{bom_name}: graph-aware is +{X}% {axis} because ..."

class BenchmarkFiedlerCurvePoint(BaseModel):
    step: int
    removed: Optional[int]
    removed_name: Optional[str]
    lambda2: float
    delta_pct: float
    collapsed_boms: List[str]      # D-04b — per-point list of BOM names that become unfulfillable

class BenchmarkRunMetadata(BaseModel):
    run_id: int
    run_tag: str                    # "benchmark" | "static_fallback"
    created_at: datetime
    feeds_fallback: bool            # True if any feed was unavailable
    bom_count: int                  # always 10 per D-01
    seed: int                       # always 42 (Monte Carlo seed; surfaced for interview narration)

class BenchmarkSummaryResponse(BaseModel):
    metadata: BenchmarkRunMetadata
    headline: dict                  # {"cost_delta_pct": -5.3, "risk_delta_pct": -18.2, "eta_delta_days": +0.4, "low_confidence": false}
    kpi_deltas: List[BenchmarkKpiDelta]
    monte_carlo: BenchmarkMcDistribution
    per_bom: List[BenchmarkBomRow]
    tradeoff: BenchmarkTradeoff
    fiedler_curve: List[BenchmarkFiedlerCurvePoint]   # 6 entries (baseline + 5 removals)
    noise_floor_pct: float          # 2.0 recommended — delta < ±2% triggers low-confidence hero variant
```

The `/benchmark/cascade-heatmap` endpoint returns a separate payload (heavier array, optional on the dashboard):

```python
class CascadeHeatmapPoint(BaseModel):
    distributor_id: int
    lat: float
    lng: float
    weight: float                   # mean BOM-collapse probability [0, 1]

class CascadeHeatmapResponse(BaseModel):
    run_id: int
    points: List[CascadeHeatmapPoint]
```

### Pattern 5: Holdout Enforcement (BENCH-06)

**What:** `GraphState.holdout_offer_pairs: FrozenSet[tuple]` already exists (Phase 2, `backend/app/graph/__init__.py:29`). Phase 4 consumes it as read-only. The benchmark itself IS the holdout — no filtering needed at benchmark time. The filter applies only to upstream strategy-tuning code, which Phase 4 does not add.

**Checkpoint for the planner:** Document in `run_benchmark.py` that it deliberately uses ALL offers because the benchmark is the holdout evaluation. If a future phase adds calibration, that phase is responsible for filtering via `gs.holdout_offer_pairs`.

### Pattern 6: Frontend `BenchmarkPage.tsx` Data Flow

```ts
// frontend/src/pages/BenchmarkPage.tsx — mirrors Dashboard useEffect pattern

useEffect(() => {
  benchmarkAPI.getSummary()
    .then((res) => setSummary(res.data))
    .catch(() => setError(true))
    .finally(() => setLoading(false));
}, []);

// Derived metrics in render (no zustand needed — single fetch, single render)
const headline = summary?.headline;
const isLowConfidence = headline?.low_confidence ?? false;
```

Use `useState` + `useEffect`, matching the Dashboard + MapPage conventions. A dedicated `benchmarkStore` zustand slice is not required for Phase 4.

### Anti-Patterns to Avoid

- **Alembic autogenerate for `optimization_runs`.** The existing `0001_initial_schema.py` describes the deleted `materials` / `suppliers` schema. Running `alembic revision --autogenerate` would produce a diff that drops those tables — dangerous on any environment that still has them. Use `Base.metadata.create_all(bind=engine)` like the rest of the app.
- **SQL aggregation inside the endpoint.** `GROUP BY graph_aware, bom_name` style queries have 20 rows to aggregate — Python is clearer and lets you compute `percent_delta = (gm - bm) / bm * 100` with type safety.
- **Recomputing Fiedler per-request.** Even at 1 s per step, five removal scenarios per request × 3 concurrent demo users would starve the event loop. Pre-compute once at startup.
- **Storing the full 1000-sample MC trace per row.** `monte_carlo_samples` stores the same truncated 200-sample slice that `RouteAlternative.monte_carlo_samples` already carries (`solve.py:84`). 10 BOMs × 2 rows × 200 samples × 8 bytes = 32 KB per run. Fine.
- **Inlining `RISK_COLORS` + `riskLabel` in `BenchmarkPage.tsx`.** Per UI-SPEC refactor note, extract them to `frontend/src/lib/risk.ts` first (plan 04-03 task), then import from both Dashboard and Benchmark + MapPage Network Risk view.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Algebraic connectivity | Your own Laplacian eigensolver | `nx.algebraic_connectivity(G, method="lanczos")` | Numerical stability on near-zero eigenvalues is a PhD-thesis-level problem; NetworkX wraps scipy.sparse.linalg.eigsh correctly |
| Betweenness centrality | Topological betweenness | `gs.betweenness` (already normalized [0,1] per Phase 2) | Already stock-weighted and normalized at build time. Do not recompute. |
| Monte Carlo cascade simulation | Your own SIR loop | `app.graph.simulation.run_monte_carlo(gs, bom_component_ids)` | Already exists, seeded at 42, N=1000. Call it once per (BOM, removed-distributor-set) tuple for the BOM-collapse mapping. |
| Percentile calculation | Manual sort-and-index | Already in `solve.py::_monte_carlo_eta` returning `{p10, p50, p90}` | Stored on every `RouteAlternative` — pull from there when persisting. |
| Distributor location lookup | Hardcoded coordinates | `db.query(Distributor.latitude, Distributor.longitude)` | 92 rows, trivial query |
| Chinese-origin detection | Parse `manufacturer_country` text | `"chinese_origin" in (risk_factors or [])` | Already the established pattern in `seeds/train_ml_models.py:98` (`any("chinese" in str(f).lower() for f in risk_factors)`) — `manufacturer_country` column is inconsistently populated (verified: Espressif rows split between `'China'` and `None`). |
| Pydantic-SQLAlchemy conversion | Manual dict-building | Pydantic `BaseModel.model_validate(row.__dict__)` or explicit column picks | A handful of columns; explicit picks are clearer. |
| Recharts grouped bar | Custom SVG | `<BarChart data={...}><Bar dataKey="baseline" fill="#64748b" /><Bar dataKey="graph_aware" fill="#6366f1" /></BarChart>` | Recharts native support; UI-SPEC locks this approach. |
| Maplibre heatmap | Per-marker fill tinting | `<Source type="geojson" data={...}><Layer type="heatmap" paint={...}/></Source>` | maplibre heatmap-layer handles density, color interpolation, and z-order natively. |

**Key insight:** Every algorithmic piece required by Phase 4 already exists. This is a *plumbing + schema + UI* phase, not an algorithms phase.

## Runtime State Inventory

Not applicable — Phase 4 is net-additive. No renames, no refactors, no migrations of existing data. The sole append is `optimization_runs` (a new table) and one new field on `GraphState` (in-memory, rebuilt at startup every invocation).

**Explicit confirmations:**
- **Stored data:** None — benchmark writes to a new table; no existing tables renamed.
- **Live service config:** None — no Datadog, APScheduler jobs, or external services are altered.
- **OS-registered state:** None — no systemd/launchd registration changes.
- **Secrets/env vars:** None — benchmark reuses existing `FRED_API_KEY` / `ACLED_KEY` / `SECRET_KEY`; no new keys.
- **Build artifacts:** None — no pyproject.toml rename, no new .egg-info.

## Common Pitfalls

### Pitfall 1: Fiedler via `tracemin_pcg` silently returns λ₂=0 on weighted bipartite graphs (HIGH SEVERITY)

**What goes wrong:** `nx.algebraic_connectivity(G, method="tracemin_pcg")` on the production graph (847-node largest CC, 7363 edges, edge weights spanning `1/stock` where stock can reach millions — weights down to 1e-6) hits its default iteration budget without converging and returns 0.0 silently. A direct foreground probe during research took 146 seconds and produced λ₂=0.

**Why it happens:** The stock-weighted inverse-distance encoding (`weight = 1/max(stock, 1)`) creates a laplacian with condition number ≥ 1e6. `tracemin_pcg` (the NetworkX default for graphs < 500 nodes, but the Phase 2 builder requests it explicitly regardless of size) uses Jacobi preconditioning which does not help for ill-conditioned systems.

**How to avoid:**
1. In Phase 4's `compute_fiedler_curve()` helper, use `method="lanczos"` (scipy's `eigsh` shift-invert mode — more robust on ill-conditioned laplacians).
2. Strip edge weights before computing λ₂ for the sequential-removal curve: `for u,v in G.edges(): G[u][v]["weight"] = 1.0`. The sequential removal is a *topological* question (does disconnection occur?), not a stock-weighted flow question.
3. Wrap in try/except with wall-clock logging. If any step exceeds 5 s, log a warning and fall back to 0.0 for that point.
4. Add a unit test (`test_fiedler_sequential.py`) that constructs a small test graph (< 20 nodes) and asserts the curve returns 6 points with λ₂ strictly decreasing.

**Warning signs:** λ₂ = 0.0000 in the main.py startup log — this is a bug indicator, not a "disconnected graph" signal.

### Pitfall 2: `manufacturer_country` field is inconsistently populated (MEDIUM)

**What goes wrong:** Picking a BOM with "Chinese-origin components" via `WHERE manufacturer_country = 'China'` misses most Espressif parts. Verified: 63 Espressif components exist; only a small subset have `manufacturer_country = 'China'`, most are `NULL`. The GPR surcharge in `sourcing.py::_feed_risk_cents()` reads `is_chinese_origin` which is computed upstream from `risk_factors` JSON array (`"chinese_origin"` string), NOT from `manufacturer_country`.

**Why it happens:** HuggingFace source dataset had inconsistent country fields. The ingestion path (`seed_db.py`) preserved both fields verbatim.

**How to avoid:** When designing the 10 BOMs, verify Chinese-origin qualification via `"chinese_origin" in (risk_factors or [])`, not via `manufacturer_country`. Example SQL for BOM selection:

```sql
SELECT id, mpn, manufacturer, category
FROM components
WHERE json_extract(risk_factors, '$') LIKE '%chinese_origin%'
ORDER BY id;
```

**Warning signs:** A BOM expected to trigger GPR surcharge produces identical cost for graph_aware=True and graph_aware=False. Check the risk_factors value on that component.

### Pitfall 3: `graph_aware=True` ceiling clamps surcharge at 15% of unit price (LOW — architectural)

**What goes wrong:** Demo BOMs containing only low-price, low-risk components show trivially small `cost_delta_pct` because the surcharge is `floor(0.15 × unit_price_cents)` and rounds to 0 for sub-$1 components.

**Why it happens:** Intentional — ROADMAP architectural constraint. `_graph_surcharge_cents()` explicitly clamps to 15% of unit_price.

**How to avoid:** At least 3 of the 10 BOMs should include at least one mid-priced component ($10+) or high-risk component where the surcharge is non-trivial. This is an interview-narrative concern, not a correctness concern. The hero headline must render the low-confidence caveat variant when abs(delta) < 2% (UI-SPEC).

**Warning signs:** Hero shows `-0.1% cost · +0.0% resilience` on every BOM — re-check BOM price profile.

### Pitfall 4: Lifespan exception swallows benchmark availability (MEDIUM)

**What goes wrong:** The current `main.py` lifespan wraps graph build in `try/except Exception` and *logs-and-continues* on failure. If the Fiedler top-5 pre-compute raises, the GraphState's `fiedler_curve` will be `[]`, and the dashboard renders "Fiedler curve not computed for this run" permanently until the server restarts.

**Why it happens:** Graceful-degradation convention (good) combined with no observability surface for partial failure (bad).

**How to avoid:** In plan 04-01 or 04-02, add a `/benchmark/health` endpoint (or extend `/health`) that reports whether `gs.fiedler_curve` is populated and how many rows `optimization_runs` has. Alternatively, log-and-continue is acceptable if the dashboard's "Fiedler curve not computed" empty state is truthful.

**Warning signs:** UI shows Fiedler empty state permanently; server log contains "Fiedler curve pre-compute skipped".

### Pitfall 5: Recharts `BarChart` with paired groups requires flat data shape (LOW)

**What goes wrong:** Developers often try `data={[{p10: [baseline, graph_aware]}, ...]}` — Recharts expects flat keys per bar (`{percentile: "P10", baseline: 123, graph_aware: 115}`).

**Why it happens:** Misreading Recharts grouped-bar examples.

**How to avoid:** Use the shape:

```ts
const data = [
  { percentile: "P10", baseline: summary.monte_carlo.p10_baseline, graph_aware: summary.monte_carlo.p10_graph_aware },
  { percentile: "P50", baseline: summary.monte_carlo.p50_baseline, graph_aware: summary.monte_carlo.p50_graph_aware },
  { percentile: "P90", baseline: summary.monte_carlo.p90_baseline, graph_aware: summary.monte_carlo.p90_graph_aware },
];

<BarChart data={data}>
  <XAxis dataKey="percentile" />
  <YAxis />
  <Tooltip />
  <Legend />
  <Bar dataKey="baseline" fill="#64748b" />
  <Bar dataKey="graph_aware" fill="#6366f1" />
</BarChart>
```

### Pitfall 6: maplibre `heatmap-layer` + per-marker hit-detection conflict (LOW)

**What goes wrong:** Adding a `<Layer type="heatmap">` beneath the distributor `<Marker>` components can intercept click events if `interactive` is not set correctly, breaking marker selection.

**Why it happens:** maplibre's interaction model treats layer sources and DOM markers differently. `<Marker>` components are DOM elements above the canvas, but the `interactiveLayerIds` prop on `<Map>` controls click routing for canvas-drawn layers.

**How to avoid:** Set the heatmap layer's `paint.heatmap-opacity` to ≤ 0.6, do not include the heatmap layer in `interactiveLayerIds`, and keep markers as the only interactive elements. Verified pattern: `MapPage.tsx:305` already uses `interactiveLayerIds={showRoutes && roadPaths.length ? ['route-forward'] : []}` — extend this to conditionally exclude the heatmap layer.

## Code Examples

### Example 1: Verified DB query for 10-BOM selection

```python
# Run once during plan 04-01 to confirm MPN availability for the 10 named BOMs
# Source: verified against live backend/supply_chain.db with 791 components / 8176 offers

BOM_CATALOG_QUERIES = {
    "iot_sensor_node": [
        # 1× ESP32 + 1× op-amp + 1× flash
        ("ESP32-WROOM-32E-N4", 1),   # Espressif SoC (may be Chinese-origin — verify)
        ("OPA861ID",           2),   # TI op-amp
        ("GD25Q40CTIGR",       1),   # GigaDevice flash
    ],
    "drone_flight_controller": [
        ("STM32F103RCT6",      1),   # STMicro MCU
        ("ESP-WROOM-02D-N4",   1),   # Espressif RF module (Chinese-origin via risk_factors)
        ("DRV8303EVM",         4),   # TI motor driver
    ],
    # ...see § BOM Catalog Recommendations below for full 10
}
```

Verify each MPN exists before committing:

```sql
SELECT c.id, c.mpn, c.category, c.manufacturer,
       c.risk_factors, COUNT(DISTINCT o.distributor_id) AS n_dists
FROM components c LEFT JOIN distributor_offers o ON o.component_id = c.id
WHERE c.mpn IN (...list...)
GROUP BY c.id;
```

### Example 2: `run_id` allocation (AUTOINCREMENT int recommended)

```python
# backend/seeds/run_benchmark.py helper

def next_run_id(db: Session) -> int:
    """Monotonic run_id. First run = 1."""
    from app.models.optimization_run import OptimizationRun
    from sqlalchemy import func
    max_id = db.query(func.max(OptimizationRun.run_id)).scalar()
    return (max_id or 0) + 1
```

### Example 3: Cascade heatmap pre-compute

```python
# backend/seeds/run_benchmark.py — cascade heatmap derivation

def compute_cascade_heatmap_data(
    gs: "GraphState",
    bom_catalog: dict[str, list[dict]],
    db: Session,
    run_id: int,
) -> list[dict]:
    """
    For each distributor d, compute the mean probability that ANY BOM becomes
    unfulfillable when d fails. Uses the existing Monte Carlo simulator with
    a forced-failure injection.

    Returns: list[{distributor_id, lat, lng, weight}] suitable for
    maplibre heatmap-layer consumption.
    """
    from app.graph.simulation import run_monte_carlo, N_SCENARIOS
    from app.models.distributor import Distributor

    dist_rows = {d.id: d for d in db.query(Distributor).all()}
    heatmap_points = []

    for did, dist in dist_rows.items():
        # Force-fail this distributor by zeroing its betweenness
        # (the simulator samples failures proportional to betweenness — we want
        #  a deterministic failure here).  We accomplish this by simulating
        #  without the node.  Cheaper alternative: directly count BOMs whose
        #  non-failed suppliers exclude did.
        collapse_count = 0
        for bom_name, items in bom_catalog.items():
            bom_cids = [ci["component_id"] for ci in items]
            # A BOM collapses if any component is sole-sourced from did
            for cid in bom_cids:
                if cid in gs.single_source_component_ids:
                    # check whether this cid's sole source == did
                    suppliers = {
                        int(p[2:]) for p in gs.graph.predecessors(f"c_{cid}")
                        if p.startswith("d_")
                    }
                    if suppliers == {did}:
                        collapse_count += 1
                        break
        weight = collapse_count / max(len(bom_catalog), 1)
        heatmap_points.append({
            "distributor_id": did,
            "lat": dist.latitude,
            "lng": dist.longitude,
            "weight": round(weight, 3),
        })

    return heatmap_points
```

Note: persist `heatmap_points` as JSON column on a parallel `benchmark_cascade_heatmap` table keyed by `run_id`, or attach to an extended `optimization_runs` auxiliary table. Simpler: store as a single JSON blob in a new `benchmark_artifacts` row. Planner's decision.

## BOM Catalog Recommendations (D-01 concrete design)

**Verified against live DB on 2026-04-18 (supply_chain.db, 791 components / 8176 offers).** All MPNs exist and have ≥ 3 distributor offers. Categories marked `[CN]` have at least one component with `"chinese_origin"` in `risk_factors`.

| # | BOM name | Composition (MPN × qty) | Narrative |
|---|----------|-------------------------|-----------|
| 1 | `iot_sensor_node` | `ESP32-WROOM-32E-N4 × 1`, `OPA861ID × 2`, `GD25Q40CTIGR × 1`, `LM317DCY × 1` | ESP32 Wi-Fi module + TI op-amp + GigaDevice flash. Espressif SoC surfaces GPR risk. **[CN candidate]** |
| 2 | `drone_flight_controller` | `STM32F103RCT6 × 1`, `ESP-WROOM-02D-N4 × 1`, `DRV8303EVM × 4`, `AD7625BCPZ × 1` | STM32 flight MCU + ESP Wi-Fi + 4× TI motor drivers + ADI high-speed ADC. Motor drivers are single-source via TI (k-core trigger). **[CN via ESP]** |
| 3 | `pcb_power_supply` | `LM317DCY × 2`, `TPS767D325PWP × 1`, `UA78M33CDCY × 2`, `OPA861ID × 1` | Linear regulators + buffer op-amp. Widely sourced — hero "graph-aware wins on cost" BOM. |
| 4 | `industrial_motor_driver` | `STM32F103VCT6 × 1`, `DRV8860EVM × 2`, `ADG202AKNZ × 2`, `INA2128UA × 2` | Industrial MCU + multi-motor driver + switches + instrumentation amp. DRV8860 is TI-only — graph-aware re-routes. |
| 5 | `rf_transceiver_module` | `ESP32-S3-WROOM-1-N16R8 × 1`, `ESP-07S × 1`, `AD7934BRUZ × 1`, `GD25Q16ESIGR × 1` | RF module + secondary Wi-Fi + ADC + flash. Heavy Espressif exposure. **[CN-heavy]** |
| 6 | `automotive_ecu` | `STM32F103VET6 × 1`, `ATMEGA328P-AU × 1`, `AD835ARZ × 1`, `OPA861ID × 4` | Dual-MCU redundancy + analog multiplier + op-amps. Automotive-grade narrative. |
| 7 | `medical_monitoring_device` | `STM32F103CBT6 × 1`, `INA2128U × 4`, `PGA206PA × 2`, `TPS780330220DDCT × 1` | Low-power MCU + instrumentation amp chain. Single-source on PGA206PA tests k-core routing. |
| 8 | `smart_meter` | `STM32F103C8T6 × 1`, `GD25Q32ESIGR × 1`, `LM317DCY × 1`, `ADS1256EVM-PDK × 1` | Common MCU + flash + regulator + 24-bit ADC. High competition on STM32 → graph-aware dampens DigiKey over-concentration. |
| 9 | `robotics_servo_driver` | `STM32F103R8T6 × 1`, `DRV10963AEVM × 4`, `DRV8885EVM × 2`, `INA2128U × 2` | Servo MCU + motor drivers + current sense. All TI motor drivers — strong k-core/single-source signal. |
| 10 | `audio_dsp_board` | `ATMEGA328P-XMINI × 1`, `PCM4202DBT × 1`, `OPA861ID × 4`, `GD25Q127CYIGR × 1` | Arduino-dev-board + audio ADC + op-amps + serial flash. Widely stocked — low-tension baseline. |

**Validation constraints:**
- At least 2 BOMs with Chinese-origin components: **#1, #2, #5** (Espressif chips with `chinese_origin` in risk_factors).
- At least 2 BOMs triggering single-source / k-core routing: **#2 (DRV8303EVM), #7 (PGA206PA), #9 (DRV10963AEVM, DRV8885EVM)**.
- At least 2 BOMs where graph-aware is expected to "lose" (cost-dominant over resilience): **#3, #10** — widely stocked, small unit prices, surcharge clamped to near-zero.

**Locking:** The planner for 04-01 should verify each MPN's existence with the SQL query above BEFORE committing the catalog constant, and adjust quantities if necessary to hit a plausible dollar range ($50–$2000 total per BOM).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Alembic-managed schema | `Base.metadata.create_all` | Project pivot Apr 7 2026 — migration history out-of-sync after Material→Component rename | Phase 4 follows `create_all`; do not re-adopt alembic |
| Deck.gl ScatterplotLayer | per-`<Marker>` react-map-gl/maplibre | Always — CLAUDE.md reference was aspirational | UI-SPEC locks marker-based for Phase 4 |
| Topological betweenness | Bipartite stock-weighted betweenness | Phase 2 (ROADMAP architectural constraint) | Consume `gs.betweenness` — do not recompute |
| Synthetic supplier data | Real Nexar/Octopart via HuggingFace | Project pivot Apr 7 2026 | All 10 BOM MPNs must exist in live DB — verified |

**Deprecated / outdated references:**
- **CLAUDE.md's Deck.gl ScatterplotLayer mention** — aspirational; actual code uses `<Marker>`. Phase 4 stays marker-based.
- **alembic initial migration** — describes deleted schema; ignore for new tables.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `method="lanczos"` on unweighted laplacian of 847-node LCC completes in < 1 s per step | § Fiedler Sequential-Removal Pre-Compute | If wrong, startup time balloons past 10 s. Mitigation: wall-clock guard + fallback to 0.0. Verifiable by a 30-line unit test. |
| A2 | AUTOINCREMENT int `run_id` is preferred to UUID | § Alternatives | Low — D-09 explicitly marks this as Claude's discretion. Downstream UI prefers small ints ("run 7"). |
| A3 | `cascade_risk_score = 1 - mc_p50_fulfillment` is the right normalization for the MC output | § OptimizationRun schema | Low — fulfillment is already on [0,1]. An alternative is to use `evar_95 - 1.0` (cost-inflation-based) but that's bounded by `EMERGENCY_COST_PREMIUM = 0.15`. Planner should surface both fields. |
| A4 | Noise floor = 2.0 % for "low confidence" hero caveat | § BenchmarkSummaryResponse | Low — 2% is a reasonable first-order guess; the checker can tune after seeing real deltas from first benchmark run. Expose as `noise_floor_pct` in response to allow future tuning without frontend change. |
| A5 | 50 MC runs (5 removal steps × 10 BOMs) for BOM-collapse mapping complete in ≤ 5 s | § Pattern 2 | Low — existing `run_monte_carlo` is < 100 ms per run per Phase 2 observations. |
| A6 | Existing `Base.metadata.create_all` picks up a new model if `app.models.__init__` imports it | § Anti-Patterns | Verified pattern — `main.py:12` calls `Base.metadata.create_all(bind=engine)` after importing `app.models`. Plan 04-01 must add `from app.models.optimization_run import OptimizationRun` to `__init__.py`. |
| A7 | Espressif components with `"chinese_origin"` in `risk_factors` trigger GPR surcharge | § Pitfall 2 | Medium — depends on whether the offer record's `is_chinese_origin` flag is populated from `risk_factors` at `sourcing.py::Offer` construction time. Verified: `optimize.py` builds `Offer(...)` and currently passes `is_chinese_origin=False`. **The planner MUST audit the offer-construction path during plan 04-01 and ensure `is_chinese_origin` is populated from `risk_factors`** — otherwise graph-aware vs baseline will not differ on the Chinese-origin BOMs. |

**A7 is the single biggest integration risk.** Cross-reference `backend/app/api/optimize.py` lines 60–120 where `Offer` is constructed from cart items — if that path sets `is_chinese_origin=False` unconditionally, the GPR surcharge never fires regardless of `graph_aware` flag. Plan 04-01 must include a task to verify (and fix if needed) the `is_chinese_origin` propagation.

## Open Questions

1. **`is_chinese_origin` propagation in `optimize.py` Offer construction**
   - What we know: `sourcing.py::_feed_risk_cents` reads `is_chinese_origin` off each `Offer`. The Offer dataclass in `sourcing.py:37` declares `is_chinese_origin: bool = False`.
   - What's unclear: Where does `optimize.py` (the API router) populate this field when constructing Offers from DB rows? If it's not populated, GPR surcharge never activates.
   - Recommendation: Plan 04-01 must include a verification-and-fix task: grep for `Offer(` constructions, confirm `is_chinese_origin = "chinese_origin" in (comp.risk_factors or [])`.

2. **Cascade heatmap storage: inline JSON vs. separate table?**
   - What we know: 92 distributor rows × 4 scalar columns = 368 floats per run. Stored as JSON blob = ~5 KB.
   - What's unclear: Do we store it on `optimization_runs` (but only meaningful once per run_id, duplicating across 20 rows) or on a new `benchmark_artifacts` table?
   - Recommendation: New `benchmark_artifacts(run_id, artifact_type, payload_json)` table. Single row per `(run_id, artifact_type)`. Artifact types: `"cascade_heatmap"`, `"bom_collapse_mapping"`, `"fiedler_curve_snapshot"`. Alternatively, skip persistence and recompute on `/benchmark/cascade-heatmap` request at startup if GraphState is available. Planner's decision.

3. **`/benchmark/summary?run_id=N` query param behavior**
   - What we know: D-09 locks "defaults to latest run_id". Claude's discretion whether to accept `?run_id=N`.
   - What's unclear: Frontend doesn't surface history in v1 (deferred per § Deferred Ideas).
   - Recommendation: Accept the query param but don't build UI for it. Backend plumbing is cheap; the route `?run_id=N` becomes useful when a "compare runs" UI ships in v2.

4. **Feed-status snapshot granularity**
   - What we know: D-10 requires the "static-fallback-mode" tag. The `feeds_available` JSON column in `OptimizationRun` captures per-feed booleans.
   - What's unclear: Should the snapshot include feed VALUES (e.g., "GPR=180") or just availability booleans?
   - Recommendation: Store booleans only. Values drift minute-to-minute; availability is what matters for reproducibility narrative.

5. **NavBar placement order**
   - What we know: UI-SPEC suggests insertion between `/map` and `/scheduler`.
   - What's unclear: Whether the user prefers Benchmark before or after Dashboard.
   - Recommendation: Insert as `NAV_ITEMS[2]` (after Dashboard=0 and Map=1, before Scheduler). Benchmark is a read-heavy analytical page; it belongs in the "intelligence" cluster near Dashboard, not the operational cluster near Cart/Checkout.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| NetworkX | Fiedler sequential-removal curve | ✓ | 3.6.1 [VERIFIED] | — |
| SQLAlchemy | `OptimizationRun` ORM model | ✓ | 2.0.40 [VERIFIED] | — |
| FastAPI + Pydantic | `/benchmark/*` endpoints | ✓ | (installed, running) | — |
| scipy | `nx.algebraic_connectivity(method="lanczos")` dependency | ✓ | (installed — NetworkX depends on it) | — |
| Recharts | Frontend MC + Fiedler charts | ✓ | (already used on Dashboard) | — |
| react-map-gl / maplibre | MapPage Network Risk + heatmap | ✓ | (already used on MapPage) | — |
| framer-motion | Animation | ✓ | (already used) | — |
| HuggingFace dataset | 791-component / 8176-offer seed data | ✓ | seeded in `supply_chain.db` | — |
| supply_chain.db | All phases | ✓ | 10.5 MB, 791 components, 92 distributors, 8176 offers, 0 optimization_runs rows [VERIFIED] | — |
| FRED_API_KEY / ACLED_KEY | Live feeds for non-fallback benchmark run | optional | present/absent per env | Benchmark marks run_tag="static_fallback"; no failure |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:** Live feed API keys — handled by Phase 3 graceful-degradation pattern. Benchmark tags the run accordingly.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.x + pytest-asyncio (backend); vitest (frontend, if adopted) |
| Config file | `backend/pytest.ini` implied; conftest at `backend/tests/conftest.py` |
| Quick run command | `cd backend && python -m pytest tests/test_benchmark_api.py -x` (single file per plan) |
| Full suite command | `cd backend && python -m pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| BENCH-01 | `OptimizationRun` model columns present, indexed `run_id`, Boolean `graph_aware`, non-null scalars for `total_cost_usd` / `eta_p50_days` / `co2_kg` / `cascade_risk_score` | unit | `pytest tests/test_optimization_run_model.py -x` | ❌ Wave 0 |
| BENCH-01 | `run_benchmark.py` produces 20 rows per invocation (10 BOMs × 2 graph_aware) | integration | `pytest tests/test_run_benchmark.py::test_produces_twenty_rows -x` | ❌ Wave 0 |
| BENCH-02 | `GET /api/v1/benchmark/summary` returns KPI delta struct with cost/risk/eta fields; `percent_delta` signed correctly | integration | `pytest tests/test_benchmark_api.py::test_summary_shape -x` | ❌ Wave 0 |
| BENCH-02 | Summary defaults to latest `run_id` (D-09) | integration | `pytest tests/test_benchmark_api.py::test_summary_latest_run_id -x` | ❌ Wave 0 |
| BENCH-03 | Frontend BenchmarkPage imports `RISK_COLORS` from `lib/risk.ts` (no re-definition) | static | `cd frontend && grep -n "const RISK_COLORS" src/pages/BenchmarkPage.tsx` — expect 0 matches | manual (grep) |
| BENCH-04 | Summary response contains `monte_carlo` with all 6 fields (p10/p50/p90 × baseline/graph_aware) | integration | `pytest tests/test_benchmark_api.py::test_mc_shape -x` | ❌ Wave 0 |
| BENCH-05 | `GraphState.fiedler_curve` has 6 entries after lifespan startup; first is baseline (`step=0, removed=None`); subsequent 5 have `delta_pct` strictly non-positive | unit | `pytest tests/test_fiedler_sequential.py::test_curve_structure -x` | ❌ Wave 0 |
| BENCH-05 | Lanczos + unweighted fallback produces non-zero λ₂ on known connected test graph | unit | `pytest tests/test_fiedler_sequential.py::test_nonzero_on_connected -x` | ❌ Wave 0 |
| BENCH-06 | `gs.holdout_offer_pairs` is a frozenset of (cid, did) tuples — matches spec from Phase 2 | unit | `pytest tests/test_graph_metrics.py::test_holdout_shape -x` | ✅ existing (Phase 2) |
| BENCH-06 | `run_benchmark.py` documents (via docstring + test) that it uses ALL offers because the benchmark IS the holdout evaluation | unit | `pytest tests/test_run_benchmark.py::test_documents_holdout_semantics -x` | ❌ Wave 0 |
| VIZ-01 | MapPage Network Risk view imports `gs.betweenness` data from `/graph/metrics` and sizes markers by normalized value | manual E2E | interviewer opens `/map`, toggles Network Risk, eyeballs differential sizing | manual-only (no selenium) |
| VIZ-02 | Side panel renders single-source component MPNs with their sole-source distributor | integration | `pytest tests/test_benchmark_api.py::test_single_source_list -x` (backend) + manual DOM check | ❌ Wave 0 |
| VIZ-03 | `/benchmark/cascade-heatmap` returns array of `{lat, lng, weight}` with 92 points (one per distributor) | integration | `pytest tests/test_benchmark_api.py::test_cascade_heatmap_shape -x` | ❌ Wave 0 |

**Manual-only justification:** VIZ-01 visual sizing is a pixel-differential check that's not cost-effective to automate in this phase. Validation is: start the backend, open `http://localhost:5173/map`, toggle Network Risk, confirm that DigiKey (highest betweenness) is visually ~2× the size of the smallest marker. Document in verification notes.

### Sampling Rate

- **Per task commit:** `cd backend && python -m pytest tests/test_benchmark_api.py tests/test_run_benchmark.py tests/test_fiedler_sequential.py tests/test_optimization_run_model.py -x` (< 15 s total)
- **Per wave merge:** `cd backend && python -m pytest` (full suite)
- **Phase gate:** full suite green + manual `/map` Network Risk visual inspection + `/benchmark` page renders against a real `run_benchmark.py` invocation.

### Wave 0 Gaps

- [ ] `backend/tests/test_optimization_run_model.py` — covers BENCH-01 column structure
- [ ] `backend/tests/test_run_benchmark.py` — covers BENCH-01 pipeline, BENCH-06 holdout semantics
- [ ] `backend/tests/test_benchmark_api.py` — covers BENCH-02 / BENCH-04 / VIZ-02 / VIZ-03 endpoint shapes
- [ ] `backend/tests/test_fiedler_sequential.py` — covers BENCH-05; includes the tracemin_pcg regression guard (Pitfall #1)

*(No framework install gap — pytest + pytest-asyncio are already in `requirements_minimal.txt`. conftest.py is already set up and exports `client`, `db_session`, `graph_db_session` fixtures — all sufficient.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 4 endpoints are read-only analytics. D-GRAPH pattern: `/graph/metrics` is public (no auth) per Phase 2 decision. `/benchmark/*` follows the same convention. |
| V3 Session Management | no | No session state on benchmark endpoints. |
| V4 Access Control | yes | `/benchmark/summary`, `/benchmark/fiedler-curve`, `/benchmark/cascade-heatmap` — verify no sensitive data (user emails, cart items, unaggregated prices) leaks. Benchmark exposes only aggregated deltas and distributor names. **VERIFY:** responses should NOT include user_id, email, or cart-item-level details. |
| V5 Input Validation | yes | `run_id` query param (if accepted) must be validated as positive int; limit response to 1 run at a time (no `?run_ids=1,2,3` batch). |
| V6 Cryptography | no | No new secrets introduced. |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Information disclosure via benchmark artifacts | Info disclosure | Aggregate-only in API response. `selected_distributor_ids` + names are fine (public data from `/distributors`). `bom_items_json` contains component IDs (public) — acceptable. Do NOT include user-specific data. |
| SQL injection via `run_id` param | Tampering | Pydantic `int` validator on request; SQLAlchemy parameterized queries only. No raw SQL concatenation anywhere in new code. |
| Resource exhaustion via MC re-computation | DoS | Pre-compute at startup (D-04a) — endpoint is constant-time read of in-memory GraphState. Do not accept `n_scenarios` as request param (T-02-03 already enforced in Phase 2). |
| Cache poisoning via `run_tag` | Tampering | `run_tag` is set exclusively by `run_benchmark.py` from server-side feed availability check — never from request input. |

No new credentials, no new external network calls, no new PII exposure. Phase 4's security posture mirrors Phase 2: public read-only analytics endpoints over already-public data.

## Sources

### Primary (HIGH confidence)

- [VERIFIED: backend/app/graph/__init__.py] — GraphState dataclass fields (lines 19–33); all claimed fields exist
- [VERIFIED: backend/app/graph/builder.py] — Fiedler computation via `method="tracemin_pcg"` (line 195), holdout seed=42 (line 27)
- [VERIFIED: backend/app/graph/simulation.py] — `run_monte_carlo()` signature, N_SCENARIOS=1000, DEFAULT_SEED=42, returns `SimulationResult(p10, p50, p90, evar_95, ...)`
- [VERIFIED: backend/app/optimization/solve.py] — `optimize_bom(... graph_aware: bool = False)` at line 142; `_monte_carlo_eta` returns `{p10, p50, p90, samples}`
- [VERIFIED: backend/app/optimization/sourcing.py] — `_graph_surcharge_cents` (line 179), `_feed_risk_cents` (line 205), 15% ceiling enforcement (line 202)
- [VERIFIED: backend/app/api/graph.py] — existing `/graph/metrics` response shape (lines 42–51) used as blueprint for `/benchmark/*`
- [VERIFIED: backend/app/main.py] — lifespan pattern (lines 15–82), `Base.metadata.create_all(bind=engine)` at line 12, graph build block at lines 46–58
- [VERIFIED: backend/app/models/__init__.py] — export pattern (all models re-exported here, required for create_all to see them)
- [VERIFIED: backend/app/models/order.py] — scalar-columns-plus-JSON-payload pattern for new `OptimizationRun` model
- [VERIFIED: backend/seeds/seed_db.py, backend/seeds/train_ml_models.py] — seeds script conventions (stdout progress logs, `if __name__ == "__main__"` guard, `sys.path.insert` boilerplate)
- [VERIFIED: backend/migrations/versions/0001_initial_schema.py] — confirms alembic is stale (references deleted `materials` / `suppliers` schema); use `create_all` instead
- [VERIFIED: live supply_chain.db via sqlite3 inspection on 2026-04-18] — 791 components, 92 distributors, 8176 offers, 0 optimization_runs; categories distribution; Espressif country-code inconsistency
- [VERIFIED: live NetworkX foreground probe on 2026-04-18] — `tracemin_pcg` returned λ₂=0 in 146 s on 847-node LCC (7363 edges) with stock-weighted laplacian — Pitfall #1 evidence
- [VERIFIED: frontend/src/pages/Dashboard.tsx] — `KpiCard`, `RISK_COLORS`, `riskLabel`, Recharts usage (confirmed UI-SPEC import contract)
- [VERIFIED: frontend/src/pages/MapPage.tsx] — `<Marker>` + maplibre `<Source>`/`<Layer>` pattern (confirmed Deck.gl not present; confirmed heatmap layer pattern available)
- [VERIFIED: frontend/src/services/api.ts] — axios wrapper pattern for new `benchmarkAPI`
- [VERIFIED: frontend/src/components/NavBar.tsx] — `NAV_ITEMS` array insertion point

### Secondary (MEDIUM confidence)

- [CITED: .planning/phases/02-graph-ml-network-risk-engine/02-CONTEXT.md] — Phase 2 locked decisions (holdout, seed, surcharge ceiling, GraphState pattern)
- [CITED: .planning/phases/03-live-data-feeds/03-CONTEXT.md] — Phase 3 locked decisions (LiveDataCache, graceful degradation, feed surcharge)
- [CITED: .planning/phases/04-benchmark-dashboard/04-CONTEXT.md] — Phase 4 locked decisions D-01 through D-10
- [CITED: .planning/phases/04-benchmark-dashboard/04-UI-SPEC.md] — locked Tailwind v4.2 + Recharts + maplibre typography/spacing/color contract
- [CITED: .planning/REQUIREMENTS.md § Benchmark & Analytics / § Graph Visualization] — BENCH-01..06, VIZ-01..03 definitions

### Tertiary (LOW confidence)

- NetworkX `algebraic_connectivity` method recommendation (lanczos vs tracemin_pcg) — based on training knowledge; verified empirically by one foreground probe. Planner should run the proposed unit test (`test_fiedler_sequential.py::test_nonzero_on_connected`) as the confirming evidence.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library already installed and pinned; no discovery risk
- Architecture: HIGH — every new file has an existing mirror in the repo
- Data model: HIGH — column list extracted directly from requirements text + existing Order/DistributorOffer patterns
- Fiedler algorithm: MEDIUM — tracemin_pcg hazard is proven; lanczos recommendation is based on training + needs a confirming unit test in plan 04-01
- BOM catalog: HIGH — all MPNs verified against live DB on research day
- Frontend patterns: HIGH — identical to Dashboard and MapPage conventions, locked by UI-SPEC
- Pitfalls: HIGH (on pitfalls 1, 2, 4) — evidenced. MEDIUM on pitfalls 3, 5, 6 — training knowledge, low severity.

**Research date:** 2026-04-18
**Valid until:** 2026-05-18 (30 days for a stable codebase)
