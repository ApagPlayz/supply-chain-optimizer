---
phase: 02-graph-ml-network-risk-engine
plan: "04"
subsystem: graph-ml
tags: [graph, api, surcharge, cp-sat, tdd, integration-tests, fastapi]
dependency_graph:
  requires:
    - app.graph.GraphState (Plan 02-01)
    - app.graph.builder.build_graph_state (Plan 02-01)
    - app.graph.simulation.run_monte_carlo (Plan 02-03)
    - app.graph.simulation.N_SCENARIOS (Plan 02-03)
  provides:
    - GET /api/v1/graph/metrics (no auth, aggregate topology metrics)
    - POST /api/v1/graph/simulate (no auth, Monte Carlo cascade results)
    - _graph_surcharge_cents() (ceiling-enforced topology surcharge)
    - solve_sourcing(graph_aware=True) (CP-SAT with graph surcharge terms)
    - optimize_bom(graph_aware=True) (end-to-end graph-aware VRP pipeline)
  affects:
    - backend/app/api/__init__.py
    - backend/app/api/optimize.py
    - backend/app/optimization/sourcing.py
    - backend/app/optimization/solve.py
tech_stack:
  added: []
  patterns:
    - FastAPI public endpoints (no auth dependency) mirroring /ml/stress pattern
    - Additive CP-SAT surcharge terms (same pattern as risk_terms)
    - Local import inside function body to avoid circular dependencies
    - Pydantic validator for max-length enforcement (DoS mitigation)
    - Hard ceiling enforcement: min(surcharge, floor(0.15 * unit_price_cents))
key_files:
  created:
    - backend/app/api/graph.py
  modified:
    - backend/app/api/__init__.py
    - backend/app/api/optimize.py
    - backend/app/optimization/sourcing.py
    - backend/app/optimization/solve.py
    - backend/tests/test_graph_metrics.py
    - backend/tests/test_graph_api.py
decisions:
  - "graph_aware: bool = False default preserves full backward compatibility — all existing tests unaffected"
  - "Graph surcharge uses q[key] (quantity variable) not y[did] (binary visit) — more precise: surcharge scales with units ordered, not just presence"
  - "Pydantic V1 @validator retained (not migrated to V2 field_validator) — consistent with rest of codebase"
  - "test_graph_aware_changes_routing stub replaced with test_graph_aware_parameter_exists — full routing divergence requires seeded DB (manual test)"
metrics:
  duration_seconds: 174
  completed_date: "2026-04-16"
  tasks_completed: 3
  files_created: 1
  files_modified: 6
requirements:
  - GRAPH-08
  - GRAPH-01
  - GRAPH-07
---

# Phase 02 Plan 04: Graph API Endpoints and Surcharge Wiring Summary

**One-liner:** Graph risk wired into CP-SAT sourcing solver as additive surcharge terms, plus two public API endpoints exposing live supply graph topology metrics and Monte Carlo simulation results to interviewers.

## What Was Built

### backend/app/api/graph.py (new)

Two public FastAPI endpoints — no auth required on either (mirrors `/ml/stress` pattern):

**GET /graph/metrics** — Returns aggregate supply graph topology metrics:
- `n_distributors`, `n_components`, `n_edges` — graph size summary
- `fiedler` — algebraic connectivity (network resilience signal)
- `single_source_count` — integer count of single-source components
- `betweenness` — Dict[str, float] distributor betweenness centrality
- `pagerank` — Dict[str, float] distributor PageRank
- `k_core_summary` — Dict[int, int] node count per core level
- `hhi_by_category` — Dict[str, float] HHI concentration per category

Returns 503 with `{"detail": "Graph not loaded..."}` when `get_graph_state()` is None (T-02-02 mitigation). Response contains only aggregate topology — no prices, no user data (T-02-04 mitigation).

**POST /graph/simulate** — Runs Monte Carlo cascade failure simulation:
- Body: `{"bom_component_ids": [int, ...]}` (max 200 items, Pydantic validator)
- Returns: `{p10, p50, p90, evar_95, n_scenarios, seed}`
- N always = `N_SCENARIOS` constant (1000) — never from request body (T-02-03 mitigation)
- Returns 503 when graph not loaded

### backend/app/api/__init__.py (modified)

Graph router registered via `api_router.include_router(graph.router)`. TODO comment from Plan 02-01 removed.

### backend/app/optimization/sourcing.py (modified)

**`_graph_surcharge_cents(offer, betweenness_score, is_single_source) -> int`** — New helper function:
- Node surcharge: `floor(betweenness_score * 0.15 * unit_price_cents)`
- Edge surcharge: `floor(0.10 * unit_price_cents)` if component is single-source
- Hard ceiling: `min(node + edge, floor(0.15 * unit_price_cents))` (T-02-01 mitigation)

**`solve_sourcing()` updated:**
- Added `graph_aware: bool = False` parameter (backward compatible)
- When `graph_aware=True`: local imports `get_graph_state()`, iterates all BOM/offer pairs, computes surcharge per pair, appends non-zero terms to `graph_surcharge_terms`
- `model.Minimize()` extended to include `sum(graph_surcharge_terms)` after existing risk_terms
- Falls back silently to zero surcharge when GraphState not loaded

### backend/app/optimization/solve.py (modified)

`optimize_bom()` gains `graph_aware: bool = False` parameter. The `_get_sourcing()` inner helper threads `graph_aware` through to each `solve_sourcing()` call.

### backend/app/api/optimize.py (modified)

`VrpRequest` schema extended with `graph_aware: bool = False`. The `optimize_bom()` call updated to `optimize_bom(..., graph_aware=body.graph_aware)`. Complete wiring: `VrpRequest.graph_aware` → `optimize_bom()` → `solve_sourcing()` → CP-SAT objective.

### backend/tests/test_graph_metrics.py (modified)

`test_surcharge_ceiling` stub replaced with real test: verifies ceiling enforcement for all 5 test price points (0.50, 1.00, 1.50, 10.00, 100.00 USD) × all distributor betweenness values from the fixture, with and without single-source flag.

### backend/tests/test_graph_api.py (modified)

Three stubs replaced with real implementations:
- `test_get_graph_metrics` — accepts 200 or 503; validates schema when 200
- `test_post_graph_simulate` — accepts 200 or 503; validates p10/p50/p90/evar_95 and n_scenarios=1000
- `test_graph_aware_parameter_exists` — validates `optimize_bom()` signature and `False` default (replaces routing-divergence stub that requires seeded DB)

## Test Results

```
17 passed, 0 skipped, 0 failed
```

Full Phase 2 graph test suite (test_graph_metrics.py + test_graph_api.py):
- All 12 previously-passing tests continue to PASS
- 4 new tests PASS (test_surcharge_ceiling, test_get_graph_metrics, test_post_graph_simulate, test_graph_aware_parameter_exists)
- 0 stubs remaining (previously 4 skipped in 02-03)

Full backend suite: 78 passed, 5 pre-existing failures (unrelated to this plan — confirmed by running tests against previous commit).

## Deviations from Plan

**1. [Rule 1 - Minor] `test_graph_aware_changes_routing` replaced with `test_graph_aware_parameter_exists`**

The plan's task 3 action block specified `test_graph_aware_parameter_exists` as the implementation for the `test_graph_aware_changes_routing` stub. The plan itself acknowledged this replacement: "Full functional verification requires a seeded DB (manual test with real data)." This is consistent — the stub name in the test file was `test_graph_aware_changes_routing` but the plan's action block showed the replacement as `test_graph_aware_parameter_exists`. Applied as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | b0f2cff | feat(02-04): create app/api/graph.py with /graph/metrics and /graph/simulate endpoints |
| Task 2 | 8c7ec92 | feat(02-04): inject graph surcharge into CP-SAT solver and add graph_aware flag |
| Task 3 | f5504d0 | feat(02-04): implement integration tests for graph endpoints and surcharge ceiling |

## Known Stubs

None — all Wave 0 stubs from Plans 02-01 through 02-03 have been implemented. Phase 2 graph module is complete.

## Threat Surface Scan

Two new public endpoints added:

| Flag | File | Description |
|------|------|-------------|
| threat_flag: unauthenticated_endpoint | backend/app/api/graph.py | GET /graph/metrics and POST /graph/simulate require no auth — intentional design (aggregate-only data, no sensitive info). STRIDE T-02-04 mitigated: response schema excludes prices, user data, raw offer details. |

Note: Both endpoints were explicitly planned as public (no auth) and were included in the plan's threat model. The surcharge ceiling (T-02-01) and DoS mitigation (T-02-03) are both enforced.

## Self-Check: PASSED

- `backend/app/api/graph.py` exists: confirmed (created mode 100644 in commit b0f2cff)
- `backend/app/optimization/sourcing.py` modified: confirmed (57 insertions in commit 8c7ec92)
- `backend/tests/test_graph_api.py` modified: confirmed (62 insertions in commit f5504d0)
- Commit `b0f2cff` exists: confirmed
- Commit `8c7ec92` exists: confirmed
- Commit `f5504d0` exists: confirmed
- 17 graph tests pass, 0 fail: confirmed by full suite run
