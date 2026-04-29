---
phase: 05-prophet-demand-forecasting
plan: 03
subsystem: forecast-api-frontend
tags: [forecast-api, frontend, recharts, sparkline, scheduler-page, bulk-endpoint, tdd]
one-liner: "Bulk GET /forecasts/all endpoint + SchedulerPage sparkline and stock-out badges using fixed-size Recharts LineChart (no ResizeObserver pathology)"
dependency-graph:
  requires: [05-02]
  provides: [FORE-03]
  affects: [frontend/src/pages/SchedulerPage.tsx, backend/app/api/forecasts.py]
tech-stack:
  added: [recharts LineChart/Line (fixed 80x24 px), ForecastData/ForecastPoint Pydantic schemas]
  patterns: [bulk-fetch on mount via Promise.all, 2-query N+1-free endpoint, TDD RED/GREEN]
key-files:
  created:
    - backend/app/api/forecasts.py
    - backend/tests/test_forecast_api.py
  modified:
    - backend/app/api/__init__.py
    - frontend/src/services/api.ts
    - frontend/src/pages/SchedulerPage.tsx
decisions:
  - "Used import type { ForecastData } to satisfy verbatimModuleSyntax TypeScript config"
  - "Fixed width={80} height={24} integers (not ResponsiveContainer) to avoid 791 ResizeObserver instances per RESEARCH.md Pattern 4"
  - "Single Promise.all fetch on mount; forecasts failure is caught and logged without blocking component list load"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-28"
  tasks-completed: 2
  tasks-total: 3
  files-created: 2
  files-modified: 3
---

# Phase 05 Plan 03: Forecast API and Frontend Sparklines Summary

## What Was Built

**Endpoint:** `GET /api/v1/forecasts/all` — public, unauthenticated, bulk read. Returns one entry per component with 12 forecast points and a precomputed `weeks_until_stockout` value. Executes exactly 2 SQL queries (one for all ComponentForecast rows ordered by component_id + forecast_date, one for total stock aggregation via SUM grouping) — no N+1 pattern.

**Stock-out formula (`compute_weeks_until_stockout`):** Clips negative Prophet yhat values to 0 before averaging the last 4 forecast points. Returns `None` for zero demand (no badge), `0.0` for zero stock with positive demand ("Out of stock"), or `total_stock / avg_demand` otherwise.

**Frontend:** `forecastsAPI.all()` client added to `api.ts`. `SchedulerPage` fetches forecasts in the same `Promise.all` as components/categories on mount. `ForecastSparkline` renders a `<LineChart width={80} height={24}>` with `isAnimationActive={false}` and no `<ResponsiveContainer>` — avoids 791 simultaneous ResizeObserver instances. `StockOutBadge` renders red badges for `weeks_until_stockout` in (0, 12] or zero stock.

## Files

| File | Change |
|------|--------|
| `backend/app/api/forecasts.py` | Created — router, schemas, endpoint, stockout formula |
| `backend/app/api/__init__.py` | Added `forecasts` import + `include_router(forecasts.router)` |
| `backend/tests/test_forecast_api.py` | Created — 10 tests (5 unit + 5 integration) |
| `frontend/src/services/api.ts` | Added `ForecastPoint`, `ForecastData` interfaces, `forecastsAPI` |
| `frontend/src/pages/SchedulerPage.tsx` | Added imports, state, updated useEffect, ForecastSparkline, StockOutBadge, sparkline+badge row per card |

## Commits

| Hash | Message |
|------|---------|
| 463a608 | test(05-03): add failing tests for forecasts API (TDD RED) |
| 8abfdfa | feat(05-03): implement GET /forecasts/all bulk endpoint (TDD GREEN) |
| e886e86 | feat(05-03): add forecastsAPI client + SchedulerPage sparkline and stock-out badge |

## TDD Gate Compliance

- RED gate (463a608): `test(05-03)` commit with 10 failing tests.
- GREEN gate (8abfdfa): `feat(05-03)` commit — all 10 tests pass.
- Wave 0 stubs (`test_stockout_formula_zero_demand`, `test_stockout_formula_zero_stock`, `test_stockout_formula_normal`, `test_forecast_endpoint_registered`) now PASS instead of SKIP.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TypeScript verbatimModuleSyntax type import**
- **Found during:** Task 2 build (`npm run build`)
- **Issue:** `ForecastData` imported as a value import but used only as a type; TypeScript `verbatimModuleSyntax` config rejects this
- **Fix:** Split into `import { componentsAPI, forecastsAPI }` + `import type { ForecastData }` from `'../services/api'`
- **Files modified:** `frontend/src/pages/SchedulerPage.tsx`
- **Commit:** e886e86

### Out-of-scope Pre-existing Failures

`tests/test_feeds.py` — `ModuleNotFoundError: No module named 'openpyxl'`. Pre-existing, unrelated to this plan. Logged to deferred items. Not fixed.

## Phase 5 Success Criteria Status

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Importing prophet code raises no errors (FORE-01 from 05-01) | PASS |
| 2 | Training script generates forecasts for all 791 components (FORE-02 from 05-02) | PASS |
| 3 | Scheduler page shows sparkline + stock-out badge per component card (FORE-03 from 05-03) | PASS (pending browser checkpoint) |

## Browser Checkpoint (Task 3)

**Status:** Awaiting human verification. The automated stack is complete:
- API endpoint implemented and tested
- Frontend builds clean (`npm run build` exits 0)
- No `<ResponsiveContainer>` in SchedulerPage (avoids ResizeObserver pathology)
- Exactly 1 call to `/forecasts/all` on mount

Human must verify: sparklines visible on cards, badges render for stock-out components, no console errors, scroll smooth across 791 cards, existing search/filter/add-to-cart flow intact.

Phase exit: ready for `/gsd-verify-work 05` after browser checkpoint approval.

## Self-Check: PASSED

- `backend/app/api/forecasts.py` exists: FOUND
- `backend/tests/test_forecast_api.py` exists: FOUND
- `backend/app/api/__init__.py` contains `forecasts.router`: FOUND
- `frontend/src/services/api.ts` contains `forecastsAPI`: FOUND
- `frontend/src/pages/SchedulerPage.tsx` contains `isAnimationActive={false}`: FOUND
- Commit 463a608 (RED): FOUND
- Commit 8abfdfa (GREEN): FOUND
- Commit e886e86 (frontend): FOUND
