---
phase: 05-prophet-demand-forecasting
plan: 01
subsystem: backend-schema
tags: [prophet, forecasting, sqlalchemy, alembic, schema, tdd]
one_liner: "SQLAlchemy ORM models + Alembic 0002 migration for Prophet demand forecasting tables, prophet pin fixed to 1.3.0, Wave 0 test scaffold with 5 passing FORE-01 tests"
dependency_graph:
  requires:
    - backend/app/core/database.py (Base, engine, SessionLocal)
    - backend/migrations/versions/0001_initial_schema.py (down_revision chain)
    - backend/tests/conftest.py (pytest fixtures, db_session)
  provides:
    - backend/app/models/forecast.py (ComponentDemandHistory, ComponentForecast ORM classes)
    - backend/migrations/versions/0002_forecast_tables.py (Alembic revision 0002)
    - backend/tests/test_forecasts.py (Wave 0 FORE-01/02/03 test scaffold)
  affects:
    - backend/app/models/__init__.py (new exports registered)
    - backend/requirements.txt (prophet pin updated)
tech_stack:
  added: []
  patterns:
    - SQLAlchemy ORM with loose FK (Integer component_id, no ForeignKey constraint — matches DistributorOffer pattern)
    - Alembic manual migration chaining (0001 -> 0002, no autogenerate)
    - pytest.importorskip for future-plan test contracts
key_files:
  created:
    - backend/app/models/forecast.py
    - backend/migrations/versions/0002_forecast_tables.py
    - backend/tests/test_forecasts.py
    - backend/tests/test_forecast_models.py
  modified:
    - backend/app/models/__init__.py
    - backend/requirements.txt
decisions:
  - "Loose FK pattern: component_id is plain Integer (no ForeignKey constraint), matching DistributorOffer.component_id pattern"
  - "prophet pin updated from 1.1.4 to 1.3.0 to match installed venv; eliminates show_progress TypeError"
  - "Wave 0 tests use pytest.importorskip for FORE-02/03 stubs — auto-activates when 05-02 and 05-03 land"
  - "TDD RED/GREEN applied for Task 1: test_forecast_models.py written before forecast.py"
metrics:
  duration: "26 minutes"
  completed_date: "2026-04-27"
  tasks_completed: 3
  tasks_total: 3
  files_created: 4
  files_modified: 2
---

# Phase 05 Plan 01: Forecast Schema Foundation Summary

## What Was Built

Created the data foundation for Prophet demand forecasting: two new SQLAlchemy ORM tables, the Alembic migration that creates them, the requirements.txt fix that aligns the prophet pin with the installed venv version (1.3.0), and the Wave 0 test scaffold covering FORE-01/FORE-02/FORE-03 behaviors.

## Files Created

| File | Purpose |
|------|---------|
| `backend/app/models/forecast.py` | ComponentDemandHistory (52-row weekly drawdown) and ComponentForecast (12-row Prophet predictions) ORM classes |
| `backend/migrations/versions/0002_forecast_tables.py` | Alembic revision 0002, chains after 0001, creates both tables with 3 indexes |
| `backend/tests/test_forecasts.py` | Wave 0 scaffold: 5 FORE-01 tests pass, 8 FORE-02/03 tests cleanly skipped |
| `backend/tests/test_forecast_models.py` | TDD RED phase test file for Task 1 (kept as regression baseline) |

## Files Modified

| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Added ComponentDemandHistory and ComponentForecast to imports and `__all__` |
| `backend/requirements.txt` | Fixed `prophet==1.1.4` → `prophet==1.3.0` (matches installed venv) |

## Schema Delta

Two new tables created by migration 0002:

**component_demand_history**
- `id` (Integer PK)
- `component_id` (Integer, NOT NULL, indexed: `ix_demand_history_component_id`)
- `week_date` (DateTime(timezone=True), NOT NULL, indexed: `ix_demand_history_week_date`)
- `demand_units` (Float, NOT NULL)

**component_forecasts**
- `id` (Integer PK)
- `component_id` (Integer, NOT NULL, indexed: `ix_component_forecasts_component_id`)
- `forecast_date` (DateTime(timezone=True), NOT NULL)
- `predicted_demand` (Float, NOT NULL)
- `lower_bound` (Float, nullable — yhat_lower from Prophet)
- `upper_bound` (Float, nullable — yhat_upper from Prophet)
- `created_at` (DateTime(timezone=True), server_default=now())

Three new indexes total.

## Test Status

| Category | Count | Status |
|----------|-------|--------|
| FORE-01 tests | 5 | PASSED |
| FORE-02 tests | 3 | SKIPPED (module not yet delivered by 05-02) |
| FORE-03 tests | 5 | SKIPPED (module not yet delivered by 05-03) |
| **Total** | **13** | **5 passed / 8 skipped / 0 failed** |

The 8 skipped tests use `pytest.importorskip` — they auto-activate without file edits when `seeds.train_forecasts` (05-02) and `app.api.forecasts` (05-03) land.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | a39526e | feat(05-01): add ComponentDemandHistory and ComponentForecast ORM models |
| 2 | 6884b47 | feat(05-01): add Alembic migration 0002 for forecast tables |
| 3 | aec6eba | test(05-01): add Wave 0 test scaffold for FORE-01 / FORE-02 / FORE-03 |

## Note for 05-02 Executor

Before running `python -m seeds.train_forecasts`, the live database must be migrated:

```bash
cd backend && venv/bin/alembic upgrade head
```

This is idempotent. The migration creates `component_demand_history` and `component_forecasts` in `supply_chain.db`. Without this step, the training script will fail with `OperationalError: no such table`.

## Deviations from Plan

None — plan executed exactly as written.

The alembic CLI commands required `SECRET_KEY` env var (Alembic env.py imports `app.models` which triggers `Settings()` validation). This is expected behavior, not a bug. The plan's verify commands ran correctly once the env var was passed. Not tracked as a deviation since this is pre-existing project behavior.

## Known Stubs

None. This plan delivers schema-only (ORM + migration). The Wave 0 tests are intentionally skipped for FORE-02/03 behaviors — these are contracts for future plans, not stubs.

## Threat Flags

None. New tables hold no PII (synthetic demand integers and aggregated forecasts only). Migration uses `op.drop_index` before `op.drop_table` in downgrade to avoid orphaned indexes (T-05-01-01 mitigated).

## Self-Check: PASSED

All files exist on disk. All commits verified in git log.

| Check | Result |
|-------|--------|
| backend/app/models/forecast.py | FOUND |
| backend/migrations/versions/0002_forecast_tables.py | FOUND |
| backend/tests/test_forecasts.py | FOUND |
| backend/tests/test_forecast_models.py | FOUND |
| .planning/phases/05-prophet-demand-forecasting/05-01-SUMMARY.md | FOUND |
| Commit a39526e (Task 1) | FOUND |
| Commit 6884b47 (Task 2) | FOUND |
| Commit aec6eba (Task 3) | FOUND |
