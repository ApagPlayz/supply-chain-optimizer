---
phase: 02-graph-ml-network-risk-engine
plan: "03"
subsystem: graph-ml
tags: [graph, monte-carlo, simulation, cascade-failure, tdd, evar, reproducibility]
dependency_graph:
  requires:
    - app.graph.GraphState
    - app.graph.builder.build_graph_state
    - backend/tests/conftest.py::graph_db_session
  provides:
    - app.graph.simulation.run_monte_carlo
    - app.graph.simulation.SimulationResult
    - app.graph.simulation.N_SCENARIOS
    - app.graph.simulation.EMERGENCY_COST_PREMIUM
  affects:
    - backend/app/api/graph.py (Plan 02-04 will import run_monte_carlo)
tech_stack:
  added: []
  patterns:
    - TDD red-green (RED commit fd28b4d, GREEN commit eceb207)
    - Isolated random.Random(seed) -- no shared RNG state contamination
    - Module-level constant for DoS mitigation (T-02-03)
    - TYPE_CHECKING guard to avoid circular imports
key_files:
  created:
    - backend/app/graph/simulation.py
  modified:
    - backend/tests/test_graph_metrics.py
decisions:
  - "N_SCENARIOS=1000 is a module constant, never a function parameter exposed to API -- T-02-03 DoS mitigation"
  - "random.Random(seed) isolates simulation RNG from all other module state -- reproducibility without global side effects"
  - "EVaR pairs fulfillment_rates with cost_inflations before sorting to maintain correct scenario pairing"
  - "Percentile index uses int(p * n_scenarios) clamped to [0, n_scenarios-1] -- avoids off-by-one on boundary"
  - "Fixture yields p10=p50=p90=0.40 with STRESS_FACTOR=1.0 -- test fixture distributors have moderate betweenness"
metrics:
  duration_seconds: 180
  completed_date: "2026-04-16"
  tasks_completed: 2
  files_created: 1
  files_modified: 1
requirements:
  - GRAPH-07
---

# Phase 02 Plan 03: Monte Carlo Cascade Simulation Summary

**One-liner:** Monte Carlo SIR-style cascade failure simulation (N=1000, seed=42) over the bipartite supply graph, producing P10/P50/P90 fulfillment percentiles and EVaR-95 cost inflation signal with guaranteed reproducibility.

## What Was Built

### backend/app/graph/simulation.py

New module implementing the cascade failure simulation engine:

**Constants:**
- `N_SCENARIOS = 1000` -- fixed at module level; API will never expose this to callers (T-02-03)
- `DEFAULT_SEED = 42` -- ensures bit-identical output on the same DB
- `STRESS_FACTOR = 1.0` -- Phase 3 will inject live macro stress multiplier here
- `EMERGENCY_COST_PREMIUM = 0.15` -- 15% cost inflation per unfulfillable component

**SimulationResult dataclass:** p10, p50, p90 (float, 0.0-1.0), evar_95 (float >= 1.0), n_scenarios (int), seed (int)

**_get_comp_to_dists(gs, bom_component_ids):**
Traverses the DiGraph predecessors of each `c_{cid}` node to collect the set of distributor IDs that supply each BOM component. Returns `Dict[int, Set[int]]`.

**run_monte_carlo(gs, bom_component_ids, n_scenarios=N_SCENARIOS, seed=DEFAULT_SEED):**
Per-scenario algorithm:
1. Each distributor fails with probability = `min(betweenness[did] * STRESS_FACTOR, 1.0)`
2. Component is unfulfillable if its supplier set is empty or is a subset of the failed distributors
3. `fulfillment_rate = n_fulfillable / n_bom`
4. `cost_inflation = 1.0 + (n_unfulfillable / n_bom) * EMERGENCY_COST_PREMIUM`

Post-simulation aggregation:
- Sorts fulfillment_rates ascending; reads P10/P50/P90 at fixed indices
- EVaR: pairs (rate, inflation) before sorting by rate, takes worst 5% scenarios, returns mean inflation
- Empty BOM fast-path returns perfect fulfillment (1.0/1.0/1.0) immediately

**Circular import protection:** `from __future__ import annotations` + `TYPE_CHECKING` guard so GraphState is only imported at type-check time, never at runtime.

### backend/tests/test_graph_metrics.py

Three stub functions replaced with real test bodies:

**test_monte_carlo_returns_percentiles:** P10 <= P50 <= P90, all in [0,1], evar_95 >= 1.0, n_scenarios == 1000. Live output: `p10=0.400 p50=0.400 p90=0.400 evar=1.0996`

**test_monte_carlo_reproducible:** Two calls with seed=42 on the same `graph_db_session` produce bit-identical p10/p50/p90/evar_95.

**test_evar_at_95th_percentile:** evar_95 in [1.0, 1.0 + EMERGENCY_COST_PREMIUM + 0.001] = [1.0, 1.151].

## Test Results

```
12 passed, 1 skipped, 0 failed
```

Active tests (12 PASSED):
- `test_graph_state_singleton` PASS
- `test_graph_builds_from_db` PASS
- `test_graph_builds_under_2s` PASS
- `test_betweenness_centrality` PASS
- `test_pagerank_centrality` PASS
- `test_fiedler_value` PASS
- `test_kcore_decomposition` PASS
- `test_hhi_per_category` PASS
- `test_single_source_flags` PASS
- `test_monte_carlo_returns_percentiles` PASS -- p10=0.400, p50=0.400, p90=0.400, evar=1.0996
- `test_monte_carlo_reproducible` PASS -- seed=42 produces identical results across two calls
- `test_evar_at_95th_percentile` PASS -- evar_95=1.0996 in [1.0, 1.151]

Still-skipped stub (1 SKIPPED):
- `test_surcharge_ceiling` -- Plan 02-04

## Deviations from Plan

None -- plan executed exactly as written. The TDD sequence (RED commit, GREEN commit) followed the prescribed order. All three test bodies match the plan's action blocks verbatim.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 RED | fd28b4d | test(02-03): add failing Monte Carlo simulation tests (RED) |
| Task 1+2 GREEN | eceb207 | feat(02-03): implement Monte Carlo cascade simulation (GREEN) |

## Known Stubs

| File | Function | Reason |
|------|----------|--------|
| test_graph_metrics.py | test_surcharge_ceiling | Plan 02-04 will implement |
| test_graph_api.py | test_get_graph_metrics / test_post_graph_simulate / test_graph_aware_changes_routing | Plan 02-04 will implement |

These stubs do not prevent Plan 03's goal -- simulation.py is fully functional and ready for the POST /graph/simulate endpoint in Plan 02-04.

## Threat Surface Scan

No new network endpoints or auth paths introduced. `simulation.py` is a pure computation module -- no file I/O, no network calls, no DB writes. The `n_scenarios` parameter exists in the function signature for test flexibility but is never exposed to API callers (Plan 02-04 will always pass `N_SCENARIOS`).

## Self-Check: PASSED

- `backend/app/graph/simulation.py` created: confirmed (`create mode 100644`)
- `backend/tests/test_graph_metrics.py` modified: confirmed (39 insertions in RED commit)
- Commit `fd28b4d` exists: confirmed
- Commit `eceb207` exists: confirmed
- 12 tests pass, 1 skip, 0 fail: confirmed by full suite run
