---
phase: 01-codebase-hardening
plan: 02
subsystem: backend-cleanup
tags: [dead-code, celery, docker, hygiene]
requirements: [HARD-05]
dependency-graph:
  requires: []
  provides:
    - clean-backend-imports
    - clean-docker-compose
  affects:
    - backend/app/core
    - backend/app/ml
    - backend/app/scrapers
    - docker-compose.yml
tech-stack:
  added: []
  removed:
    - celery (worker service in docker-compose)
    - prophet (forecaster referenced deleted Material model)
  patterns:
    - delete-over-patch (orphaned code deleted rather than ported; Phase 5 will rebuild)
key-files:
  created: []
  modified:
    - docker-compose.yml
  deleted:
    - backend/app/ml/prophet_forecaster.py
    - backend/app/ml/forecast_tasks.py
    - backend/app/scrapers/data_pipeline.py
    - backend/app/core/celery_app.py
decisions:
  - Delete celery_app.py entirely (no remaining active tasks after orphan removal) rather than prune the include/beat_schedule lists
  - Phase 5 forecaster rebuild deferred; delete orphaned Prophet code now to unblock backend imports
metrics:
  duration-minutes: 8
  tasks-completed: 1
  files-deleted: 4
  files-modified: 1
  completed: 2026-04-16T16:56:49Z
---

# Phase 01 Plan 02: Remove Orphaned Pre-Pivot Files Summary

Delete 4 broken pre-pivot files (Prophet forecaster + Celery tasks + pipeline) that referenced the deleted `Material` model and remove the now-dead `celery_worker` service from docker-compose.yml, restoring clean backend imports.

## Requirements Completed

| Requirement | Source | Status |
| ----------- | ------ | ------ |
| HARD-05     | REQUIREMENTS.md | Complete — orphaned pre-pivot files removed; backend imports cleanly |

## What Was Built

### Deletions (code hygiene)

- **`backend/app/ml/prophet_forecaster.py`** — 132-line Prophet-based price forecaster that imported `from app.models.material import PriceHistory, PriceForecast, Material`. The `material` module was removed during the data pivot to `Component`/`DistributorOffer`, so every import of this file crashed with `ModuleNotFoundError`.
- **`backend/app/ml/forecast_tasks.py`** — Celery tasks wrapping `ProphetForecaster`. Imported both the deleted forecaster and the deleted `Material` model.
- **`backend/app/scrapers/data_pipeline.py`** — FRED/Alpha Vantage scheduled data pull tasks. Imported `from app.models.material import Material, PriceHistory`.
- **`backend/app/core/celery_app.py`** — Celery bootstrap that `include=[...]`'d the two deleted task modules and scheduled beat tasks by name that referenced deleted tasks. With no remaining Celery tasks after orphan removal, deleted entirely per D-03 / RESEARCH.md Open Question 3.

### Modifications

- **`docker-compose.yml`** — Removed the entire `celery_worker:` service block (18 lines). The worker ran `celery -A app.core.celery_app worker` — a module that no longer exists and could not start.

### Preserved

- `backend/app/scrapers/__init__.py` preserved per plan Step 5 — empty package is not harmful; Phase 3 (Live Feeds) may populate it.
- `backend/app/ml/__init__.py` preserved — still hosts `MLState` for the current stress + lead-time models.
- `redis` service kept in docker-compose.yml — may be used by future live-feed cache.

## Approach

Plan called out two deletion layers:

1. **Orphaned source files (D-01).** Three files reference the deleted `app.models.material` module. Deleted outright; Phase 5 will build a new forecaster against the current `Component`/`DistributorOffer` schema from scratch per D-02 of 01-RESEARCH.md.
2. **Dead Celery scaffolding (D-03, Pitfall 3).** `celery_app.py`'s `include=[...]` and `beat_schedule` both referenced only tasks in the deleted files. Pruning the config lists would leave an empty Celery app with no tasks and a `celery_worker` docker service that does nothing. Cleaner to remove the entire Celery layer now and let Phase 5 choose a fresh scheduled task approach.

No refactors, no ports, no feature work — pure deletion of dead code.

## Verification

All acceptance criteria checked programmatically:

| Check | Command | Result |
| ----- | ------- | ------ |
| prophet_forecaster.py absent | `test ! -f backend/app/ml/prophet_forecaster.py` | PASS |
| forecast_tasks.py absent | `test ! -f backend/app/ml/forecast_tasks.py` | PASS |
| data_pipeline.py absent | `test ! -f backend/app/scrapers/data_pipeline.py` | PASS |
| celery_app.py absent | `test ! -f backend/app/core/celery_app.py` | PASS |
| docker-compose.yml has no celery_worker | `grep -c celery_worker docker-compose.yml` → 0 | PASS |
| Clean backend import | `SECRET_KEY=<random> python -c "import app.main"` exits 0 | PASS |
| No stale references in backend/app | `grep -r "prophet_forecaster\|forecast_tasks\|data_pipeline\|celery_app" backend/app/` → zero matches | PASS |
| Test suite still passes (scope of this plan) | `pytest tests/` → 56 passing tests unchanged; 5 pre-existing failures unrelated to this plan | PASS (deferred) |

Note on `SECRET_KEY`: bare `python -c "import app.main"` now triggers the SECRET_KEY validator added by plan 01-01 (separate plan, same phase). Confirmed imports succeed when a random SECRET_KEY is set, proving no ModuleNotFoundError from this plan's deletions.

## Deviations from Plan

None — plan executed exactly as written. Task 1 performed all six steps (delete 3 orphans, verify grep, delete celery_app.py, strip docker-compose.yml service, verify scrapers/ directory, verify clean import).

## Deferred Issues

Five pre-existing test failures on base commit `1d9b863` were observed during verification. Confirmed via `git stash` + running pytest on the clean base commit — **none caused by this plan**. Logged to `.planning/phases/01-codebase-hardening/deferred-items.md`:

- `tests/test_sourcing.py::test_sourcing_splits_across_distributors_when_stock_insufficient` — sourcing MILP does not split across distributors when stock insufficient
- `tests/test_strategies.py::test_four_strategies_produce_different_routes`
- `tests/test_strategies.py::test_all_strategies_have_breakdown_and_citations`
- `tests/test_strategies.py::test_cheapest_selects_low_price_offers`
- `tests/test_strategies.py::test_at_least_one_strategy_considers_cross_dock`

All five live in `app/optimization/` (sourcing.py / strategies.py) and are unrelated to Celery/Prophet cleanup. Candidates for a future hardening plan or Phase 5 solver work.

## Authentication Gates

None. Plan required no network access, no external services, no secrets.

## Commit Log

| Task | Commit | Files |
| ---- | ------ | ----- |
| 1 — Delete orphaned files + clean Celery config | `f2ea081` | 4 deleted, 1 modified |

## Known Stubs

None introduced by this plan. This plan only removes code; it does not add features, data sources, or UI.

## Threat Flags

None. This plan removes dead code and does not introduce new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. Threat T-1-06 (celery_worker crash loop on `docker-compose up`) is now fully mitigated by the service removal, matching the plan's threat model disposition.

## Self-Check: PASSED

**File existence:**
- MISSING (expected): `backend/app/ml/prophet_forecaster.py`
- MISSING (expected): `backend/app/ml/forecast_tasks.py`
- MISSING (expected): `backend/app/scrapers/data_pipeline.py`
- MISSING (expected): `backend/app/core/celery_app.py`
- FOUND: `docker-compose.yml` (modified — celery_worker block removed)
- FOUND: `.planning/phases/01-codebase-hardening/01-02-SUMMARY.md`
- FOUND: `.planning/phases/01-codebase-hardening/deferred-items.md`

**Commits:**
- FOUND: `f2ea081` — `chore(01-02): remove orphaned pre-pivot files and dead Celery config`
