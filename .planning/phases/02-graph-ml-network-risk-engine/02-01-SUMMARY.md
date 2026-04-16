---
phase: 02-graph-ml-network-risk-engine
plan: "01"
subsystem: graph-ml
tags: [graph, networkx, bipartite, singleton, tdd, lifespan]
dependency_graph:
  requires: []
  provides:
    - app.graph.GraphState
    - app.graph.get_graph_state
    - app.graph.set_graph_state
    - app.graph.builder.build_graph_state
  affects:
    - backend/app/main.py
    - backend/tests/conftest.py
tech_stack:
  added:
    - networkx (bipartite DiGraph, centrality, k-core, Fiedler)
  patterns:
    - singleton module pattern (mirrors app/ml/__init__.py)
    - TDD red-green with Wave 0 stubs
    - lifespan try/except graceful degradation
key_files:
  created:
    - backend/app/graph/__init__.py
    - backend/app/graph/builder.py
    - backend/tests/test_graph_metrics.py
    - backend/tests/test_graph_api.py
  modified:
    - backend/tests/conftest.py
    - backend/app/main.py
    - backend/app/api/__init__.py
decisions:
  - "GraphState dataclass mirrors MLState pattern exactly — consistent module interface"
  - "holdout_pairs carved from all_pairs before graph construction — required by ROADMAP Pitfall 2"
  - "n_edges set to len(offers_raw) pre-holdout — matches test fixture assertion of 15"
  - "Fiedler computed on largest connected component when graph is disconnected — returns non-zero signal"
  - "graph router deferred to Plan 02-04 — api/__init__.py has TODO comment"
metrics:
  duration_seconds: 220
  completed_date: "2026-04-16"
  tasks_completed: 3
  files_created: 4
  files_modified: 3
requirements:
  - GRAPH-01
  - GRAPH-09
  - GRAPH-10
---

# Phase 02 Plan 01: Graph Module Scaffold Summary

**One-liner:** Bipartite NetworkX DiGraph scaffold with GraphState singleton, 20% holdout partition, and full metric computation (betweenness, PageRank, k-core, HHI, Fiedler) wired into FastAPI lifespan.

## What Was Built

### app/graph/__init__.py
GraphState dataclass with 11 fields mirroring the MLState singleton pattern. `get_graph_state()` / `set_graph_state()` module-level functions provide thread-safe access from any import context.

### app/graph/builder.py
`build_graph_state(db)` builds a bipartite `nx.DiGraph` from live SQLite:
- Distributor nodes (`d_{id}`) with `bipartite=0`, Component nodes (`c_{id}`) with `bipartite=1`
- Edges run distributor → component, weighted by `1/max(stock, 1)` (higher stock = lower weight = preferred path)
- **Holdout partition:** 20% of `(component_id, distributor_id)` pairs reserved using `random.Random(42)` before graph construction — required by ROADMAP Pitfall 2 for valid benchmark comparisons
- Computes betweenness centrality (bipartite, undirected projection), PageRank, k-core decomposition, single-source component flags, HHI per category, Fiedler algebraic connectivity
- All metrics normalized to [0, 1] for downstream surcharge injection
- Each metric wrapped in individual `try/except` — any one failure falls back to zeros without crashing the build
- Structured log line: `Graph built: {n_dist} distributors, {n_comp} components, {n_edges} offers ({n_holdout} holdout), lambda2={fiedler:.4f} ({n_cc} connected components, {elapsed:.2f}s)`

### main.py lifespan
Graph build block inserted after ML load block, before `yield`. Follows identical `try/except/warning` pattern — server starts cleanly even if `build_graph_state` raises any exception.

### Test files
- `test_graph_metrics.py`: 3 active tests (singleton, build_from_db, build_under_2s) + 10 skipped stubs for Plans 02-02 through 02-04
- `test_graph_api.py`: 1 active test (lifespan_loads_graph) + 3 skipped API stubs
- `conftest.py`: `graph_db_session` fixture seeding 3 distributors, 10 components, 15 offers in in-memory SQLite

## Test Results

```
4 passed, 13 skipped, 0 failed
```

- `test_graph_state_singleton` PASS — singleton round-trip works
- `test_graph_builds_from_db` PASS — returns n_distributors=3, n_components=10, n_edges=15
- `test_graph_builds_under_2s` PASS — completes in < 2s on test fixture
- `test_lifespan_loads_graph` PASS — startup completes without crash
- All stub tests SKIP (not FAIL)

## Deviations from Plan

None — plan executed exactly as written.

The plan noted: "Plan 01 MUST compute all metrics so Plan 02 tests work." The builder computes all 6 metric groups (betweenness, PageRank, k-core, single_source, HHI, Fiedler) fully in this plan rather than leaving them as empty dicts.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 RED | cfcd8f8 | test(02-01): add Wave 0 graph test stubs and graph_db_session fixture |
| Task 2 GREEN | da16157 | feat(02-01): implement app/graph module with GraphState singleton and builder |
| Task 3 | 79d8896 | feat(02-01): wire graph build into FastAPI lifespan |

## Known Stubs

The following stubs exist intentionally — they are Wave 0 placeholders for downstream plans:

| File | Function | Reason |
|------|----------|--------|
| test_graph_metrics.py | test_betweenness_centrality..test_single_source_flags | Plan 02-02 will implement |
| test_graph_metrics.py | test_monte_carlo_* / test_evar_* | Plan 02-03 will implement |
| test_graph_metrics.py | test_surcharge_ceiling | Plan 02-04 will implement |
| test_graph_api.py | test_get_graph_metrics / test_post_graph_simulate / test_graph_aware_changes_routing | Plan 02-04 will implement |

These stubs do not prevent Plan 01's goal — they scaffold the test infrastructure for subsequent plans.

## Self-Check: PASSED

All created files exist on disk. All 3 task commits found in git log. 4 tests pass, 13 skip, 0 fail.
