# Phase 04 — Deferred Items

Items discovered during execution that are out of scope for the current plan
and must be addressed in a future plan.

## From 04-01

### D-04-01-A: StrategyWeights missing sourcing/routing fields

**Discovered during:** Task 4 (integration test_pipeline_integration)
**File:** `backend/app/optimization/strategies.py`
**Blocker for:** Full end-to-end `run_benchmark.py` invocation against a
live-like DB (the @pytest.mark.slow integration test).

**Issue:**
`backend/app/optimization/solve.py:159` accesses `strat.us_only_sourcing`
and `getattr(strat, "transport_penalty_scale", 1.0)`; `sourcing.py` reads
`consolidation_bonus_usd` similarly. These attributes are **not defined**
on the committed `StrategyWeights` dataclass. Any call to `optimize_bom()`
raises `AttributeError: 'StrategyWeights' object has no attribute
'us_only_sourcing'`.

**Evidence:**
- `backend/tests/test_strategies.py::test_four_strategies_produce_different_routes`
  — fails on the committed worktree base with the same AttributeError.
- The main repo working tree has an **uncommitted** modification to
  `strategies.py` that adds these three fields plus per-strategy values.
  That change has never been committed.

**Why deferred here:**
- Per Rule scope boundary, pre-existing failures in files outside the plan's
  declared `files_modified` are out of scope.
- A parallel worktree agent may be actively modifying `strategies.py`;
  editing it here would race.
- The 7 fast tests in `test_run_benchmark.py` cover every BENCH-01 contract
  (catalog shape, Chinese-origin MPN coverage, next_run_id, feed snapshot,
  holdout docstring, T-04-01 / T-04-04 mitigations). The integration test
  only exercises `optimize_bom` — the same path the existing
  test_strategies.py already fails on.

**Resolution plan:**
When `strategies.py` is committed with the three missing fields, remove the
`@pytest.mark.skip` in
`backend/tests/test_run_benchmark.py::test_pipeline_integration`. No other
change needed — the skip reason auto-documents the dependency.
