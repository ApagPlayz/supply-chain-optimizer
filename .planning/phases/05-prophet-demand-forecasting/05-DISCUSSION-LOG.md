# Phase 5: Prophet Demand Forecasting - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 05-prophet-demand-forecasting
**Areas discussed:** Demand signal source, Top-20 scope, Forecast display format, Data generation strategy

---

## Demand Signal Source

| Option | Description | Selected |
|--------|-------------|----------|
| Simulated weekly stock drawdown | Seed 52-week history: start at current stock, apply noise-varied weekly consumption. Prophet learns seasonality/trend. | ✓ |
| Offer-count as demand proxy | Count weekly offer availability per component as time series. Real data but supply-side signal. | |
| Stock level as constant baseline | Use current stock as flat baseline. Near-flat forecast, not useful. | |

**User's choice:** Simulated weekly stock drawdown
**Notes:** Honest for portfolio project — demonstrating the ML pipeline, not claiming live telemetry.

---

## Consumption Rate Design

| Option | Description | Selected |
|--------|-------------|----------|
| Risk-score weighted | High-risk components draw faster; creates meaningful variance. | ✓ |
| Category-based rates | Different rates by component category. Requires hardcoded assumptions. | |
| Uniform random noise | Same base rate + random noise for all. Simpler but all forecasts look similar. | |

**User's choice:** Risk-score weighted
**Notes:** Ties the forecast signal to the existing risk model.

---

## Forecast Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All 791 components | Every component gets forecasted; every card shows sparkline. | ✓ |
| Top 100 by composite score | 13% of catalog. | |
| User-selectable threshold (FORECAST_TOP_N) | Configurable at train time. | |

**User's choice:** All 791 components
**Notes:** User explicitly expanded scope from top-20 — wants forecasting as a full catalog feature, not a demo gimmick.

---

## Forecast Display Format

| Option | Description | Selected |
|--------|-------------|----------|
| Sparkline + stock-out badge | 12-point sparkline + "Stock-out in ~N weeks" badge per card. | ✓ |
| Trend badge only | ↑/↓/→ arrow badge next to stock level. | |
| Forecast table panel | Side panel with weekly forecast table. | |

**User's choice:** Sparkline + stock-out badge on every component card
**Notes:** Every card gets the sparkline — forecasting is first-class on SchedulerPage.

---

## Data Generation & Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Seed 52-week series per component at train time | History persisted in DB before Prophet fitting. | ✓ |
| Generate history in-memory only | Faster, but training data not inspectable. | |
| Store history as JSON blob | Simpler schema, harder to query. | |

**User's choice:** Seed 52-week series per component at train time, stored in `component_demand_history` table
**Notes:** Enables inspection and replay of training data.

---

## Claude's Discretion

- Prophet seasonality parameters (weekly, yearly, holidays)
- Recharts component choice for sparkline (LineChart, AreaChart, or custom SVG)
- Stock-out threshold formula
- API endpoint path convention

## Deferred Ideas

None.
