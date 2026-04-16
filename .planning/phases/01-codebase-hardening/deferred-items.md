# Phase 01 — Deferred Items

Items discovered during plan execution that are outside the scope of the current plan.

## Pre-existing Test Failures

### test_sourcing_splits_across_distributors_when_stock_insufficient

- **Discovered during:** 01-02 (orphaned file cleanup)
- **File:** `backend/tests/test_sourcing.py::test_sourcing_splits_across_distributors_when_stock_insufficient`
- **Status:** FAILED on base commit `1d9b863` (confirmed via git stash + test run)
- **Symptom:** `assert 1 in dids and 2 in dids` — solver returns only distributor 2 when 50 units are needed and distributor 1 has only 10 stock, distributor 2 has 100 stock. Expected multi-distributor split.
- **Root cause:** Logic in `solve_sourcing` (app/optimization/sourcing.py) — not related to Celery/Prophet cleanup.
- **Scope:** Out of scope for 01-02 (orphaned file deletion). Candidate for a future hardening plan or phase-5 solver improvements.

### test_strategies.py — 4 failures

- **Discovered during:** 01-02 (orphaned file cleanup)
- **File:** `backend/tests/test_strategies.py`
- **Failing tests:**
  - `test_four_strategies_produce_different_routes`
  - `test_all_strategies_have_breakdown_and_citations`
  - `test_cheapest_selects_low_price_offers`
  - `test_at_least_one_strategy_considers_cross_dock`
- **Status:** All 4 FAILED on base commit `1d9b863` (confirmed via git stash + test run on base)
- **Root cause:** Strategy/solver logic in app/optimization/strategies.py — not related to Celery/Prophet cleanup.
- **Scope:** Out of scope for 01-02 (orphaned file deletion). Candidate for a future hardening plan or phase-5 solver work.
