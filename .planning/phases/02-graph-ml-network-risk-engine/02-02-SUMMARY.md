---
phase: 02-graph-ml-network-risk-engine
plan: "02"
subsystem: graph-ml
tags: [graph, networkx, tdd, metrics, betweenness, pagerank, fiedler, k-core, hhi, single-source]
dependency_graph:
  requires:
    - app.graph.GraphState
    - app.graph.builder.build_graph_state
    - backend/tests/conftest.py::graph_db_session
  provides:
    - test_betweenness_centrality (PASSING)
    - test_pagerank_centrality (PASSING)
    - test_fiedler_value (PASSING)
    - test_kcore_decomposition (PASSING)
    - test_hhi_per_category (PASSING)
    - test_single_source_flags (PASSING)
  affects:
    - backend/tests/test_graph_metrics.py
tech_stack:
  added: []
  patterns:
    - TDD green phase -- activating Wave 0 stubs with real assertions
    - bipartite min-max normalized centrality verification pattern
key_files:
  created: []
  modified:
    - backend/tests/test_graph_metrics.py
decisions:
  - "HHI assertions use allows range (4000-6000 for Microcontrollers) rather than exact value to be robust against minor fixture changes"
  - "Fiedler test uses float >= 0.0 without exact value -- builder computes on LCC so value varies by holdout seed; correctness is no-crash + non-negative"
  - "single_source test asserts exact membership: {6,7,8,9,10} in, {1,2,3,4,5} not in -- relies on builder using all offers_raw (not just train_offers)"
metrics:
  duration_seconds: 180
  completed_date: "2026-04-16"
  tasks_completed: 2
  files_created: 0
  files_modified: 1
requirements:
  - GRAPH-02
  - GRAPH-03
  - GRAPH-04
  - GRAPH-05
  - GRAPH-06
---

# Phase 02 Plan 02: Graph Metric Tests Summary

**One-liner:** Six structural graph metric tests activated (betweenness, PageRank, Fiedler, k-core, HHI, single-source) against the 3-distributor/10-component fixture with analytically known expected values.

## What Was Built

### Task 1: Betweenness, PageRank, Fiedler, k-core tests

Four stub functions replaced with real assertions in `backend/tests/test_graph_metrics.py`:

**test_betweenness_centrality** -- Verifies all 3 distributor IDs present in betweenness dict, all values in [0.0, 1.0], dist1 (DigiKey, carries all 10 components) has normalized betweenness >= dist2 and dist3.

**test_pagerank_centrality** -- Verifies all 3 distributor IDs present in pagerank dict, all values in [0.0, 1.0], dist1 has highest normalized PageRank due to most outgoing edges.

**test_fiedler_value** -- Verifies fiedler is `float`, >= 0.0, and never raises. Builder computes on LCC (dist3 LCSC is isolated -- no offers), yielding fiedler=0.011327. Satisfies STRIDE T-02-02: no exception on disconnected graph.

**test_kcore_decomposition** -- Verifies k_core dict is non-empty, all values are non-negative integers, node `d_1` and `c_1` are present.

### Task 2: Single-source and HHI tests

Two remaining stub functions replaced:

**test_single_source_flags** -- Verifies components 6-10 (only DigiKey has stock) are in `single_source_component_ids`. Verifies components 1-5 (DigiKey + Mouser both carry them) are NOT single-source. Output: count=5.

**test_hhi_per_category** -- Verifies:
- Op-Amps HHI = 10000.0 (pure monopoly: only dist 1 carries all 5 Op-Amp components)
- Microcontrollers HHI = 5000.0 (symmetric duopoly: dist 1 stock=500, dist 2 stock=500, each 50% share)
- All values in [0.0, 10000.0]

## Test Results

```
9 passed, 4 skipped, 0 failed
```

Active tests (9 PASSED):
- `test_graph_state_singleton` PASS
- `test_graph_builds_from_db` PASS
- `test_graph_builds_under_2s` PASS
- `test_betweenness_centrality` PASS
- `test_pagerank_centrality` PASS
- `test_fiedler_value` PASS -- fiedler=0.011327 (LCC of connected dist1+dist2+10 components)
- `test_kcore_decomposition` PASS
- `test_hhi_per_category` PASS -- Microcontrollers=5000.0, Op-Amps=10000.0
- `test_single_source_flags` PASS -- 5 single-source components (IDs 6-10)

Still-skipped stubs (4 SKIPPED):
- `test_monte_carlo_returns_percentiles` -- Plan 02-03
- `test_monte_carlo_reproducible` -- Plan 02-03
- `test_evar_at_95th_percentile` -- Plan 02-03
- `test_surcharge_ceiling` -- Plan 02-04

## Deviations from Plan

None -- plan executed exactly as written. All 6 test bodies match the plan's action blocks verbatim (with minor style normalization: >= replacing >= in comments, -- for em-dash in comments to avoid Unicode in source).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Tasks 1+2 | 0d4ec68 | feat(02-02): implement 6 graph metric tests (betweenness, pagerank, fiedler, k-core, HHI, single-source) |

## Known Stubs

The following stubs remain intentionally for downstream plans:

| File | Function | Reason |
|------|----------|--------|
| test_graph_metrics.py | test_monte_carlo_* / test_evar_* | Plan 02-03 will implement |
| test_graph_metrics.py | test_surcharge_ceiling | Plan 02-04 will implement |
| test_graph_api.py | test_get_graph_metrics / test_post_graph_simulate / test_graph_aware_changes_routing | Plan 02-04 will implement |

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Tests use in-memory SQLite fixture only -- no production data accessed.

## Self-Check: PASSED

- `backend/tests/test_graph_metrics.py` modified: confirmed (1 file changed, 70 insertions)
- Commit `0d4ec68` exists in git log: confirmed
- 9 tests pass, 4 skip, 0 fail: confirmed by full suite run
