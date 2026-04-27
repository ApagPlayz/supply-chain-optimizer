# Phase 5: Prophet Demand Forecasting - Context

**Gathered:** 2026-04-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 delivers a Prophet-based demand forecasting pipeline covering ALL 791 components. The training script seeds a 52-week synthetic demand history per component, fits Prophet models, and stores 12-week forward forecasts in the DB. The Scheduler page displays a sparkline + stock-out badge on every component card, making forecasting a first-class feature rather than a top-20 sidebar.

</domain>

<decisions>
## Implementation Decisions

### Demand Signal Source
- **D-01:** Prophet models weekly demand using a **simulated 52-week stock drawdown series** per component. Starting from current stock, each component draws down at a weekly rate determined by its `risk_score` — high-risk components (risk_score > 0.6) draw faster, low-risk components draw slowly. This creates realistic forecast variance across the catalog and is honest for a portfolio project (demonstrating the ML pipeline, not claiming live telemetry).
- **D-02:** Consumption rates are **risk-score weighted**, not uniform or category-based. This ties the forecasting signal directly to the existing risk model and produces meaningful divergence in the sparklines.

### Forecast Scope
- **D-03:** Train Prophet on **all 791 components** — not just a top-20 subset. Every component card in SchedulerPage gets a sparkline and stock-out badge. Forecasting is a full catalog feature.

### Top-20 Ranking (for ordering/prioritization only)
- **D-04:** If any ranking of components by forecast urgency is needed (e.g., API ordering), use `num_offers × risk_score` composite score descending. This is a secondary concern — all components are forecasted regardless.

### Data Storage
- **D-05:** The training script seeds a `component_demand_history` table with 52 weekly rows per component before fitting Prophet. History is persisted (not in-memory only) so training data can be inspected or replayed. Forecast outputs go into a separate `component_forecasts` table with schema: `(component_id, forecast_date, predicted_demand, lower_bound, upper_bound)`.

### Frontend Display
- **D-06:** Every component card in `SchedulerPage.tsx` shows:
  1. A **12-point sparkline** (Recharts `<LineChart>` or inline SVG) displaying the 12-week demand trend
  2. A **"Stock-out in ~N weeks" badge** when `predicted_demand` trajectory would exhaust `stock` within the horizon; no badge if stock remains healthy
- **D-07:** Non-forecasted components do not exist — all 791 are forecasted. No greyed-out states or "No forecast" rows needed.

### Training Script
- **D-08:** Invoked as `python -m seeds.train_forecasts` (mirrors `python -m seeds.train_ml_models` pattern). Seeds history + trains Prophet + writes forecasts in a single pass.

### Claude's Discretion
- Exact Prophet seasonality parameters (weekly, yearly, holidays) — choose what fits a 52-week series best
- Recharts component choice (LineChart, AreaChart, or custom SVG sparkline) — whichever is lightest for 791 inline instances
- Stock-out threshold logic (exact formula for computing N weeks) — implement as: `stock / avg_weekly_demand_last_4_weeks`
- API endpoint path (e.g., `/api/forecasts/` or `/api/components/{id}/forecast`) — follow existing route conventions

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Implementation
- `backend/app/models/component.py` — `Component` and `DistributorOffer` models; `risk_score` field drives D-02
- `frontend/src/pages/SchedulerPage.tsx` — integration target; component card layout, `ComponentItem` interface, existing state patterns
- `backend/seeds/train_ml_models.py` — training script pattern to follow for `train_forecasts.py`
- `backend/app/api/ml.py` — existing ML API route pattern to follow for forecast endpoint
- `backend/migrations/versions/0001_initial_schema.py` — reference for Alembic migration syntax; old `price_forecasts` table is dead (references `material_id`/old schema) — do not reuse

### Dependencies
- `prophet==1.1.4` — already in `backend/requirements.txt`, installed in venv
- `pandas==2.1.2`, `numpy==1.26.2` — also already present

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `risk_score` on `Component` model — primary driver for D-02 consumption rate weighting
- `stock` on `DistributorOffer` (sum per component = total available stock) — starting point for drawdown simulation
- `Recharts` — already imported in `BenchmarkPage.tsx`; use same library for sparklines in SchedulerPage
- `RISK_COLORS` / `riskLabel` in `frontend/src/lib/risk.ts` — reuse for badge color coding

### Established Patterns
- Training scripts: `python -m seeds.<name>` invocation, SQLAlchemy Session context, joblib-style saves — follow `train_ml_models.py`
- API routes: `./backend/app/api/*.py` with `APIRouter`, Pydantic response schemas in `schemas.py`
- Frontend data fetching: `componentsAPI.*` calls in `SchedulerPage.tsx` — add `forecastsAPI` to `services/api.ts` following same pattern
- Alembic migration per new table — follow `0001_initial_schema.py` style

### Integration Points
- `SchedulerPage.tsx` `ComponentItem` interface needs `forecast` field added (or fetched separately per card)
- New tables: `component_demand_history` and `component_forecasts` require a new Alembic migration
- `backend/app/models/` — add `ComponentForecast` and `ComponentDemandHistory` SQLAlchemy models

</code_context>

<specifics>
## Specific Ideas

- Sparkline: 12 data points (one per forecast week), rendered inline on each card — keep it narrow (80-100px wide, 24px tall) so it fits the existing card layout
- Stock-out badge: `bg-red-500/20 text-red-400` styling consistent with existing risk badge pattern in SchedulerPage
- History seeding: generate rows as `(component_id, week_date, demand_units)` where `demand_units = base_rate * risk_multiplier + gaussian_noise`

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-prophet-demand-forecasting*
*Context gathered: 2026-04-27*
