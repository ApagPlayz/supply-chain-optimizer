# Phase 4: Benchmark Dashboard — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 04-benchmark-dashboard
**Areas discussed:** Holdout BOM design, Dashboard hero narrative, Fiedler + Map viz approach, Honest-tradeoff storytelling, Benchmark script UX, Run persistence, Cascade viz

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Holdout BOM set design | Hand-crafted vs random vs stratified test BOMs | ✓ |
| Dashboard hero narrative | Hero headline vs equal KPIs vs A/B table | ✓ |
| Fiedler + Map viz approach | Static/interactive λ₂ card + map integration mode | ✓ |
| Honest-tradeoff storytelling | Dedicated card vs colored table vs footnote | ✓ |

**User's choice:** All four — multi-select.

---

## Holdout BOM Set Design

| Option | Description | Selected |
|--------|-------------|----------|
| N=10 hand-crafted portfolios | Named, interpretable BOMs (IoT node, PCB, drone FC, etc.); interview-friendly; deterministic | ✓ |
| N=50 random-sampled BOMs | Statistical tighter intervals but harder to narrate individual scenarios | |
| Stratified 3×3 matrix | 3 sizes × 3 risk profiles = 9 BOMs | |
| Hybrid: 5 named + 20 random | Narrative + statistical backing; more work | |

**User's choice:** N=10 hand-crafted portfolios (Recommended).
**Notes:** Interview-narratable test cases explicitly preferred over statistical N.

---

## Strategy Comparison per BOM

| Option | Description | Selected |
|--------|-------------|----------|
| Balanced-only paired A/B | graph_aware=True vs False for Balanced strategy only; cleanest narrative | ✓ |
| All 4 strategies paired | cheapest/fastest/lowest-risk/balanced × both modes; 8 rows per BOM | |
| Balanced + Risk (2 strategies) | Middle ground; shows graph-awareness matters more for risk-weighted strategies | |

**User's choice:** Balanced-only paired A/B (Recommended).
**Notes:** 20 rows per benchmark run (10 BOMs × 2 modes).

---

## Dashboard Hero Narrative

| Option | Description | Selected |
|--------|-------------|----------|
| Single hero headline + detail scroll | Giant KPI hero → 3 KPI cards → MC chart → Fiedler → tradeoff; glanceable | ✓ |
| 3 equal KPI cards above-fold | Neutral; weaker first impression | |
| Full A/B per-BOM comparison table | 10-row table; dense; requires reading | |

**User's choice:** Single hero headline + detail scroll (Recommended).
**Notes:** Selected with ASCII mockup preview confirming the layout.

---

## Fiedler Card Interactivity

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-computed top-5 curve + click-to-inspect | Startup pre-compute; click point reveals affected BOMs; no live recompute | ✓ |
| Fully interactive click-to-remove | Live λ₂ recompute endpoint; most impressive but 100–300ms per click | |
| Static ranked list, no chart | Table only; simplest; weakest visual punch | |

**User's choice:** Pre-computed top-5 curve + click-to-inspect (Recommended).
**Notes:** Backend computes curve at startup inside graph lifespan block, stored on GraphState.

---

## Map Graph Viz Integration

| Option | Description | Selected |
|--------|-------------|----------|
| View toggle on existing Map | Routes ↔ Network Risk toggle; marker-based; no Deck.gl refactor | ✓ |
| Always-on centrality sizing | Markers permanently sized by betweenness; mixes visual languages | |
| New dedicated Map sub-tab | Deck.gl ScatterplotLayer; cleanest but most refactor work | |

**User's choice:** View toggle on existing Map (Recommended).
**Notes:** Stays marker-based with react-map-gl/maplibre. Deck.gl deferred.

---

## Honest-Tradeoff Storytelling

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated "Honest Tradeoff" card | 'Where Graph-Aware Loses' card between MC chart and Fiedler card | ✓ |
| Colored delta column in per-BOM table | Red/green cells; tradeoff emerges organically | |
| Footnote / small text | Minimal visual weight | |

**User's choice:** Dedicated 'Honest Tradeoff' card (Recommended).
**Notes:** Treated as a first-class element, not a footnote. Interview signal for honesty.

---

## Monte Carlo Chart

| Option | Description | Selected |
|--------|-------------|----------|
| P10/P50/P90 cost-inflation bars, baseline vs graph-aware | Grouped bar chart; clean Recharts; reveals EVaR shrink | ✓ |
| CDF curves overlaid | More statistically honest; harder to read | |
| Histogram of fulfillment rates | Shows distribution shape; obscures EVaR narrative | |

**User's choice:** P10/P50/P90 cost-inflation bars (Recommended).

---

## run_benchmark.py Output

| Option | Description | Selected |
|--------|-------------|----------|
| DB rows + printed summary + markdown report | Writes .planning/BENCHMARK-RESULTS.md as portfolio artifact | ✓ |
| DB rows + printed summary only | No persistent report file | |
| DB rows only (silent) | Simplest; dashboard is sole surface | |

**User's choice:** DB rows + printed summary + markdown report (Recommended).

---

## optimization_runs Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Append with run_id + timestamp | History preserved; /benchmark/summary defaults to latest run_id | ✓ |
| Overwrite — only latest run exists | Simpler schema; no history | |
| Append with --clean flag | Middle ground; extra flag logic | |

**User's choice:** Append with run_id + timestamp (Recommended).

---

## Cascade Simulation Visualization

| Option | Description | Selected |
|--------|-------------|----------|
| Static heatmap overlay | Toggle on Network Risk view; color intensity = BOM-collapse probability | ✓ |
| Sequential animation | Play button animates top-5 cascading removals; impressive but timing-fussy | |
| Scenario scrubber slider | P10 → P90 slider; interactive but niche | |

**User's choice:** Static heatmap overlay (Recommended).

---

## Claude's Discretion

Areas where Claude has flexibility (no user input required):

- Exact component composition of the 10 named BOMs (name + component/qty tuples)
- NavBar.tsx tab placement order for the Benchmark tab
- run_id type (AUTOINCREMENT int vs UUID string)
- Endpoint shape for the Fiedler curve (extend /graph/metrics vs new /benchmark/fiedler-curve)
- Cascade heatmap color ramp (viridis/magma/plasma — perceptually uniform)
- Optional ?run_id=N query param on /benchmark/summary for historical comparison
- Pydantic response schemas for benchmark endpoints
- /benchmark/summary caching strategy

## Deferred Ideas

- Fully interactive click-to-remove Fiedler recompute endpoint
- Dedicated /network Map sub-tab with Deck.gl refactor
- Cascade animation / scenario scrubber
- Random-sampled large-N BOM set (--mode=statistical)
- Temporal "compare runs A vs B" frontend view
- Benchmark against SupplyGraph / ChipExplorer external datasets (v2)
