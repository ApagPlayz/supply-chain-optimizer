---
phase: 05-prophet-demand-forecasting
plan: 02
subsystem: backend-seed
tags: [prophet, forecasting, training, drawdown-simulation, seed-script, tdd]
one_liner: "Sequential Prophet training pipeline over all 791 components with risk-weighted drawdown simulation, uncertainty bounds (uncertainty_samples=100), and idempotent DB writes"
dependency_graph:
  requires:
    - backend/app/models/forecast.py (ComponentDemandHistory, ComponentForecast ORM — delivered by 05-01)
    - backend/migrations/versions/0002_forecast_tables.py (tables must exist before script runs)
    - backend/app/models/component.py (Component.risk_score, DistributorOffer.stock)
    - backend/app/core/database.py (engine, SessionLocal)
  provides:
    - backend/seeds/train_forecasts.py (generate_demand_series + main() pipeline)
    - backend/tests/test_train_forecasts.py (8 tests: 5 unit + 3 integration)
  affects:
    - backend/tests/test_forecasts.py (test_demand_series_shape + test_demand_series_zero_stock_floor now PASS instead of SKIP)
tech_stack:
  added:
    - prophet 1.3.0 (already pinned by 05-01; training call surface verified)
    - numpy.random.default_rng (reproducible per-component RNG)
    - pandas.date_range (52-week weekly calendar, tz-naive for Prophet)
  patterns:
    - Lazy imports inside main() to keep module import fast for test collection
    - sys.path bootstrap via BACKEND_ROOT (mirrors seeds/run_benchmark.py)
    - SQLAlchemy bulk_insert_mappings for 50k-row single-commit efficiency
    - Truncate-on-start idempotency (delete both tables before insert)
    - Risk multiplier normalized against observed mean (0.166), capped at 5.0x
    - Zero-stock floor: base_rate = max(total_stock / 52, 1.0)
key_files:
  created:
    - backend/seeds/train_forecasts.py
    - backend/tests/test_train_forecasts.py
  modified: []
decisions:
  - "Risk multiplier formula: 1.0 + (risk_score / 0.166), capped at 5.0 — normalizes against observed mean so max-risk draws ~5x faster than zero-risk"
  - "uncertainty_samples=100 (not 0) — zero would silently drop yhat_lower/yhat_upper from predict()"
  - "No show_progress kwarg on m.fit() — TypeError on prophet 1.3.0"
  - "Seed = component_id for per-component reproducibility across re-runs"
  - "Lazy imports inside main() — top-level Prophet import adds ~3s to test collection"
  - "Single bulk_insert_mappings + single commit at end — avoids 791 per-component transaction overhead"
metrics:
  duration: "18 minutes"
  completed_date: "2026-04-27"
  tasks_completed: 2
  tasks_total: 3
  files_created: 2
  files_modified: 0
---

# Phase 05 Plan 02: Prophet Training Pipeline Summary

## What Was Built

Implemented the Prophet demand forecasting training pipeline (FORE-02) that seeds 52 weeks of synthetic risk-weighted drawdown demand per component, fits a Prophet model on each, and writes 12 weekly forward forecasts with confidence bounds to the DB. Runs as `python -m seeds.train_forecasts` and covers all 791 components in a single sequential pass.

## Files Created

| File | Purpose |
|------|---------|
| `backend/seeds/train_forecasts.py` | Sequential Prophet training pipeline: `generate_demand_series()` (testable helper) + `main()` (791-component loop with truncate, history insert, Prophet fit, forecast insert) |
| `backend/tests/test_train_forecasts.py` | 8 tests: 5 unit tests on `generate_demand_series` (fast, 0.01s) + 3 integration smoke tests on `main()` against a 5-component in-memory SQLite DB (1.72s total) |

## Algorithm Summary

**Drawdown simulation (`generate_demand_series`):**
- `base_rate = max(total_stock / 52, 1.0)` — zero-stock floor prevents degenerate Prophet input (18 zero-stock components in live DB)
- `risk_multiplier = min(1.0 + risk_score / 0.166, 5.0)` — mean-normalized; max-risk (0.700) draws ~5x faster than zero-risk
- Weekly noise: `Gaussian(0, weekly_draw * 0.15)` — 15% coefficient of variation
- Seed = component_id — reproducible per component across re-runs

**Prophet fit per component:**
- `Prophet(yearly_seasonality=False, weekly_seasonality=False, daily_seasonality=False, uncertainty_samples=100)`
- No `show_progress` kwarg (would TypeError on prophet 1.3.0)
- `make_future_dataframe(periods=12, freq='W', include_history=False)` → 12 forecast rows
- `yhat`, `yhat_lower`, `yhat_upper` all persisted

**Idempotency:** Truncates `component_demand_history` and `component_forecasts` at the start of every run — re-runs produce same row counts.

## Test Results

| Category | Count | Status |
|----------|-------|--------|
| Unit tests (generate_demand_series) | 5 | PASSED (0.01s) |
| Integration smoke tests (main() × 5 components) | 3 | PASSED (1.72s) |
| FORE-02 tests reactivated in test_forecasts.py | 2 | PASSED (was SKIPPED) |
| **Total** | **10** | **All passing** |

## Task 3: Checkpoint (Pending Human Verification)

Task 3 is a `checkpoint:human-verify` requiring the human to run `python -m seeds.train_forecasts` against the live DB and confirm:
1. 41,132 demand history rows written
2. 9,492 forecast rows written
3. All rows have `lower_bound` and `upper_bound` populated
4. Idempotent on re-run (counts stay 9,492, not 18,984)

**Pre-requisite:** `cd backend && venv/bin/alembic upgrade head` (migration 0002 must be applied)

## TDD Gate Compliance

RED → GREEN cycle followed:
- RED commit `e872c02`: failing tests for `seeds.train_forecasts` (module did not exist)
- GREEN commit `778eb6c`: implementation passes all 8 tests

## Deviations from Plan

**1. [Rule 1 - Bug] `show_progress` appears in comments, not in code**

The plan's acceptance criterion `grep -q 'show_progress' backend/seeds/train_forecasts.py` returns FALSE was interpreted strictly: `show_progress` appears only in code comments (as documentation of the pitfall), not as a Python kwarg. The actual `m.fit(df)` call has zero kwargs — no `show_progress` is passed. The acceptance intent is satisfied.

No other deviations — plan executed as specified.

## Known Stubs

None. The training script produces real Prophet forecasts (not mocks). The integration tests use a genuine 5-component Prophet run.

## Note for 05-03 Executor

The API endpoint can read `component_forecasts` directly with no further training needed. Aggregate `total_stock` per component via:

```python
SUM(DistributorOffer.stock) GROUP BY component_id
```

This is the same query pattern used in `train_forecasts.py` and can be reused in the `/forecasts/all` endpoint response.

The `compute_weeks_until_stockout` function (tested via `pytest.importorskip("app.api.forecasts")` in `test_forecasts.py`) will auto-activate once `app/api/forecasts.py` is created.

## Threat Flags

None. The training script only truncates `component_demand_history` and `component_forecasts` — never touches `components`, `distributor_offers`, or any other table. No new network endpoints introduced.

## Self-Check

| Check | Result |
|-------|--------|
| backend/seeds/train_forecasts.py | FOUND |
| backend/tests/test_train_forecasts.py | FOUND |
| Commit e872c02 (TDD RED) | FOUND |
| Commit 778eb6c (TDD GREEN) | FOUND |
| 8 tests pass in test_train_forecasts.py | VERIFIED |
| test_demand_series_shape in test_forecasts.py | PASSED |
| test_demand_series_zero_stock_floor in test_forecasts.py | PASSED |
