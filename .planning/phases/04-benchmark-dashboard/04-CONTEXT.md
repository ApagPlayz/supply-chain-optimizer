---
phase: 04-benchmark-dashboard
created: 2026-04-18
mode: discuss
---

# Phase 4: Benchmark Dashboard — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

An interviewer can open the Benchmark tab and see real numbers — graph-aware vs. baseline A/B delta, Monte Carlo P10/P50/P90 bars, and an interactive Fiedler degradation card — all backed by a holdout scenario set. The Map page is extended with a Network Risk view: distributor markers sized by betweenness, colored by risk tier, with k-core single-source highlighting and a cascade heatmap overlay.

**Scope:** BENCH-01 through BENCH-06 + VIZ-01 through VIZ-03 (9 requirements, 4 plans).
**Not in scope:** Prophet forecasting (Phase 5), new live feeds, graph model changes, benchmark against external datasets (v2 TGNN work).

</domain>

## Prior Decisions (Locked from Phase 2 / Phase 3 / ROADMAP)

Carried forward — do not re-open:

- **Holdout partition exists** — 20% of (component_id, distributor_id) offer pairs reserved via `random.seed(42)`, stored as `frozenset` on `GraphState` from Phase 2. Phase 4 consumes this; does not re-partition.
- **Fixed MC seed = 42** for reproducible Monte Carlo runs (Phase 2 `solve.py`).
- **Surcharge ceiling = 15% of unit price** (architectural constraint). Benchmark must not exceed this when graph_aware=True.
- **Charting = Recharts** — already used across Dashboard with `ScatterChart`, `BarChart`, `PieChart`, `RadarChart`.
- **Map stack = react-map-gl/maplibre with `<Marker>` per distributor** — NOT Deck.gl. CLAUDE.md's "Deck.gl ScatterplotLayer" is aspirational; actual implementation uses per-marker components. Extend, don't replace.
- **`graph_aware: bool` flag already wired into `optimize_bom()` (Phase 2 plan 04)** — benchmark flips this flag per paired run.
- **GraphState singleton + `get_graph_state()`** — benchmark reads centrality scores, k-core membership, Fiedler value from this; no re-computation in the benchmark path.
- **Feed graceful degradation** — benchmark runs must succeed even when all live feeds are `None` (static-fallback mode); document the fallback scenario as a separate run tag.

<decisions>
## Implementation Decisions

### Holdout & Methodology

- **D-01:** Holdout BOM set = **10 hand-crafted named portfolio BOMs** (e.g. "IoT sensor node", "PCB power supply", "drone flight controller", "industrial motor driver", "RF transceiver module", "automotive ECU", "medical monitoring device", "smart meter", "robotics servo driver", "audio DSP board"). Deterministic across runs. Interview-friendly — each can be narrated by name. Exact component composition designed during planning and locked in `run_benchmark.py`.
- **D-02:** Strategy comparison = **Balanced-only paired A/B** per BOM. Each holdout BOM produces exactly two `optimization_runs` rows: `(balanced, graph_aware=False)` and `(balanced, graph_aware=True)`. 20 rows per benchmark run total. Clean headline narrative: "graph-aware cuts cost by X% at equal risk."
- **D-06 (holdout enforcement):** `run_benchmark.py` must query only non-holdout offer pairs when performing strategy tuning / preprocessing. Holdout pairs are consumed exclusively at benchmark time.

### Benchmark Pipeline & Persistence

- **D-08:** `run_benchmark.py` produces **three outputs**: (a) inserts rows into `optimization_runs`, (b) prints an aggregate summary table to stdout, (c) writes `.planning/BENCHMARK-RESULTS.md` with timestamp + deltas — this markdown is a portfolio artifact (linkable in README / resume context).
- **D-09:** `optimization_runs` table uses **append-only with `run_id` + `timestamp` columns**. Each `run_benchmark.py` invocation generates a new `run_id` (monotonic int or UUID — planner decides). `/benchmark/summary` defaults to `latest run_id`. Supports temporal comparison ("did last week's refactor change the benchmark?") without a `--clean` flag dance.

### Dashboard Layout & Story

- **D-03:** Benchmark tab hero layout:

  ```
  ┌──────────────────────────────────────────────────┐
  │   −X.X% COST  ·  +Y.Y% RESILIENCE                │
  │   at equal ETA across 10 reference BOMs          │
  ├──────────────────────────────────────────────────┤
  │ Cost Δ  │ Risk Δ  │ ETA Δ                        │
  ├──────────────────────────────────────────────────┤
  │ Monte Carlo distribution (P10/P50/P90)           │
  │ Fiedler degradation curve                        │
  │ "Where Graph-Aware Loses" tradeoff card          │
  └──────────────────────────────────────────────────┘
  ```

  Single giant headline → three KPI cards → MC chart → Fiedler card → honest-tradeoff card. One glanceable number drives the first 5 seconds.

- **D-07:** Monte Carlo chart = **grouped bar chart, P10/P50/P90 × (baseline, graph-aware)**. Recharts `BarChart` on cost-inflation axis (USD or %). Reveals graph-aware shrinking the right tail (EVaR reduction). Two color groups, six bars total per BOM (or aggregate across BOMs).

- **D-06:** Honest tradeoff display = **dedicated "Where Graph-Aware Loses" card** placed between MC chart and Fiedler card. Shows 1–2 named BOMs where graph-aware is worse on at least one objective (cost OR ETA OR risk). Interview signal: "I built this to show the full picture, not just wins." If all 10 BOMs favor graph-aware on all three axes, card still renders with the single closest-to-neutral case surfaced.

### Fiedler Degradation Card

- **D-04:** Card renders a **pre-computed top-5 sequential-removal λ₂ curve**. Line chart x-axis = removal step (0→5), y-axis = λ₂; each of the 5 points is labeled with the removed distributor name (e.g. "Remove DigiKey → −15.2%"). Clicking any point reveals which holdout BOMs become unfulfillable when that set of distributors is down.
- **D-04a:** Backend pre-computes the top-5 curve **at startup inside the graph lifespan block** (immediately after existing centrality computation in Phase 2). Stored on `GraphState.fiedler_curve: list[dict]`. No new `/graph/fiedler_remove` endpoint needed for v1 — covered by existing `/graph/metrics` payload extension + a new `GET /benchmark/fiedler-curve` or inclusion in `/benchmark/summary`.
- **D-04b:** "Which BOMs collapse" click interaction uses the already-computed Monte Carlo simulation output; no per-click re-simulation. Mapping from removed-distributor-set → affected-BOMs is produced offline by `run_benchmark.py`.

### Map Page Extension (Network Risk View)

- **D-05:** MapPage.tsx gains a **view toggle** (top-right, near NavigationControl): `[ Routes | Network Risk ]`. Route view = existing behavior unchanged. Network Risk view:
  - Distributor `<Marker>` size scaled by normalized betweenness centrality (reuse normalization from Phase 2 — already in `GraphState`).
  - Marker fill color by risk tier (reuse `RISK_COLORS` + `riskLabel()` from `Dashboard.tsx`).
  - **k-core / single-source highlighting (VIZ-02):** distributors that are the sole source of at least one k-core (single-source) component get a red halo/ring. A separate side panel lists the single-source components and their exclusive distributor — because k-core is a component-level concept, the panel is the authoritative list; marker halos are the map-side signal.
  - **No Deck.gl refactor** — stays marker-based to keep plan scope minimal.

- **D-10:** Cascade simulation (VIZ-03) = **static heatmap overlay** on Network Risk view. Toggle button "Cascade Risk" renders a heatmap gradient layer (maplibre `heatmap-layer` source or tinted marker fills) where color intensity = mean BOM-collapse probability if that distributor fails (derived from the 1000 MC runs). No animation complexity; one-shot demo-grade visual. Data computed in `run_benchmark.py` and exposed via benchmark API.

### Claude's Discretion

The planner/researcher may decide these without re-asking:

- Exact component composition of the 10 named BOMs (name + list of (component, qty) pairs). Must span categories from the 791-component dataset and include at least 2 BOMs with Chinese-origin components (to demonstrate GPR feed interaction).
- NavBar.tsx tab placement order (suggested: after Map, before Digital Twin, but planner can choose).
- Whether `run_id` is an integer AUTOINCREMENT or UUID string.
- Whether Fiedler curve is served via extending `/graph/metrics` or a new `/benchmark/fiedler-curve` endpoint.
- Precise color ramp for cascade heatmap (use a perceptually uniform gradient — viridis/magma/plasma — planner picks).
- Whether `/benchmark/summary` accepts a `?run_id=N` query param for historical comparison (nice-to-have).
- Exact Pydantic schema shapes for benchmark responses.
- Caching strategy for `/benchmark/summary` (static after startup vs. per-request query — depends on query cost).

### Folded Todos

None — no pending todos matched Phase 4 scope.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase boundary & requirements
- `.planning/ROADMAP.md` §Phase 4 — goal, success criteria, plans 04-01 through 04-04, architectural constraints (holdout, seed)
- `.planning/REQUIREMENTS.md` §Benchmark & Analytics — BENCH-01 through BENCH-06
- `.planning/REQUIREMENTS.md` §Graph Visualization — VIZ-01 through VIZ-03

### Prior phase decisions (carry-forward)
- `.planning/phases/02-graph-ml-network-risk-engine/02-CONTEXT.md` — GraphState singleton, holdout partition (seed=42), surcharge ceiling, Fiedler computation scope, `graph_aware` flag wiring, CP-SAT injection
- `.planning/phases/03-live-data-feeds/03-CONTEXT.md` — LiveDataCache usage, graceful degradation pattern, feed surcharge term
- `.planning/phases/02-graph-ml-network-risk-engine/02-04-PLAN.md` — CP-SAT graph surcharge + `/graph/metrics`, `/graph/simulate` endpoint signatures (reference for new `/benchmark/*` endpoints)

### Backend patterns to mirror
- `backend/app/graph/__init__.py` — `GraphState` singleton pattern (mirror for any new benchmark-side cache)
- `backend/app/optimization/sourcing.py` — existing `_graph_surcharge_cents()` + `_feed_risk_cents()` call sites (read-only for Phase 4; benchmark flips `graph_aware` flag, does not add new surcharge terms)
- `backend/app/optimization/solve.py` — `optimize_bom()` signature with `graph_aware: bool` param (flip in paired runs)
- `backend/app/api/graph.py` — `/graph/metrics`, `/graph/simulate` endpoint pattern (reuse shape for `/benchmark/*`)
- `backend/app/api/__init__.py` — router registration
- `backend/app/main.py` — lifespan pre-compute block (add Fiedler top-5 curve here)
- `backend/seeds/seed_db.py`, `backend/seeds/train_ml_models.py` — script conventions for `backend/seeds/run_benchmark.py`
- `backend/app/models/` — SQLAlchemy ORM conventions (for new `OptimizationRun` model)

### Frontend patterns to mirror
- `frontend/src/pages/Dashboard.tsx` — `KpiCard` (framer-motion), `RISK_COLORS`, `riskLabel()`, Recharts usage conventions
- `frontend/src/pages/MapPage.tsx` — maplibre map, `<Marker>` pattern, NavigationControl placement (toggle goes near here)
- `frontend/src/components/NavBar.tsx` — tab registration (add Benchmark tab)
- `frontend/src/services/api.ts` — API client pattern (`feedsAPI`, `componentsAPI`, `distributorsAPI`) — add `benchmarkAPI`
- `frontend/src/store/` — zustand store conventions if a `benchmarkStore` is needed

### Platform & tooling
- `CLAUDE.md` — tech stack, data sources, ML layer (note: Deck.gl reference is aspirational; current code is maplibre markers)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`KpiCard`** (Dashboard.tsx) — framer-motion animated card; copy pattern for Benchmark hero KPIs.
- **`RISK_COLORS` + `riskLabel(score)`** (Dashboard.tsx) — reuse for Network Risk marker coloring. Keep color semantics consistent across pages.
- **Recharts** — `BarChart` for Monte Carlo, `LineChart` for Fiedler curve; already in dependency tree and used on Dashboard.
- **`GraphState` singleton** — read `betweenness_centrality`, `pagerank`, `k_core_membership`, `single_source_edges`, `fiedler_value`, `holdout_pairs` directly. No new computation needed in Phase 4 except the top-5 sequential-removal Fiedler curve (one added field).
- **`optimize_bom(graph_aware: bool)`** — flip this per paired run. No solver changes.
- **`<Marker>` + maplibre** — extend existing pattern; don't introduce Deck.gl.

### Established Patterns
- **API router:** new file `backend/app/api/benchmark.py` with `APIRouter(prefix="/benchmark")` registered in `app/api/__init__.py`.
- **Seed script:** `backend/seeds/run_benchmark.py` invoked via `python -m seeds.run_benchmark`, mirrors `seed_db.py` / `train_ml_models.py` structure.
- **Lifespan pre-compute:** extend `main.py` lifespan block to compute top-5 Fiedler curve after existing graph build.
- **Frontend store:** zustand pattern already used in `cartStore`, `authStore`, `optimizeStore` — add `benchmarkStore` if client caching needed.

### Integration Points
- **NavBar.tsx** — add Benchmark tab (placement at Claude's discretion).
- **Routing (`App.tsx`)** — add `/benchmark` route pointing to new `BenchmarkPage.tsx`.
- **MapPage.tsx** — inject view-toggle control + Network Risk conditional rendering branch; do not break existing route visualization.
- **SQLAlchemy models** — new `OptimizationRun` model in `backend/app/models/`, include in `__init__.py` exports.
- **Migration** — `alembic revision --autogenerate` for the `optimization_runs` table (or direct schema add — planner decides based on existing migration strategy).

</code_context>

<specifics>
## Specific Ideas

- **Named BOMs over random sampling** — the user explicitly prefers interview-narratable test cases over statistical N. Each BOM should have a story ("drone flight controller uses a Chinese-origin ESP32 and a single-source MCU from STMicro — here's how graph-aware routing reacts").
- **Headline cannot be a blank card** — if the benchmark produces statistically insignificant deltas, the page must degrade gracefully (show deltas truthfully with low-confidence caveat rather than fake a win).
- **Honest tradeoff card is a first-class element, not a footnote** — "Where Graph-Aware Loses" is a dedicated titled card because it demonstrates honesty to interviewers more than any positive delta.
- **Demo-grade resilience** — benchmark must run with all live feeds down (static fallback); document this in the markdown report as an explicit fallback-mode run tag.

</specifics>

<deferred>
## Deferred Ideas

These came up in discussion and belong in other phases or post-v1 polish:

- **Fully interactive click-to-remove Fiedler recompute** — `POST /graph/fiedler_remove` endpoint with live λ₂ recompute. Deferred unless the static top-5 curve proves insufficient in demo feedback. Complexity not justified for v1.
- **Dedicated `/network` Map sub-tab with Deck.gl refactor** — proper ScatterplotLayer density rendering. Deferred to v2 / separate UI pass; current Phase 4 stays marker-based.
- **Cascade animation / scenario scrubber** — sequential fade-out animation of top-5 removals, or P10→P90 scenario slider. Static heatmap covers v1; animation is polish.
- **Random-sampled large-N BOM set** — supplementing the 10 named BOMs with 50 random BOMs for tighter confidence intervals. Could be a future benchmark mode (`--mode=statistical`).
- **Temporal benchmark comparison UI** — `/benchmark/summary?run_id=N` API already supports history, but a "compare runs A vs B" frontend view is out of scope.
- **Benchmark against external datasets** (SupplyGraph, ChipExplorer) — tagged v2 in REQUIREMENTS.md.

### Reviewed Todos (not folded)

None — no pending todos surfaced for this phase.

</deferred>

---

*Phase: 04-benchmark-dashboard*
*Context gathered: 2026-04-18*
