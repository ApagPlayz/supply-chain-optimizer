# Phase 5: Prophet Demand Forecasting - Research

**Researched:** 2026-04-27
**Domain:** Prophet time-series forecasting, SQLAlchemy/Alembic migrations, Recharts sparklines, FastAPI pattern extension
**Confidence:** HIGH — all critical claims verified against installed packages, live DB, and official Context7 docs

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Prophet models weekly demand using a **simulated 52-week stock drawdown series** per component. Starting from current stock, each component draws down at a weekly rate determined by its `risk_score` — high-risk components (risk_score > 0.6) draw faster, low-risk components draw slowly.
- **D-02:** Consumption rates are **risk-score weighted**, not uniform or category-based.
- **D-03:** Train Prophet on **all 791 components** — not just a top-20 subset.
- **D-04:** If any ranking is needed (e.g., API ordering), use `num_offers × risk_score` composite score descending. All 791 are forecasted regardless.
- **D-05:** Two tables: `component_demand_history` (52 weekly rows per component) and `component_forecasts` (`component_id, forecast_date, predicted_demand, lower_bound, upper_bound`). History is persisted.
- **D-06:** Every component card in `SchedulerPage.tsx` shows a 12-point sparkline and "Stock-out in ~N weeks" badge when trajectory exhausts stock.
- **D-07:** All 791 components are forecasted — no greyed-out states.
- **D-08:** Invoked as `python -m seeds.train_forecasts`.

### Claude's Discretion

- Exact Prophet seasonality parameters (weekly, yearly, holidays) — choose what fits a 52-week series best
- Recharts component choice (LineChart, AreaChart, or custom SVG sparkline) — whichever is lightest for 791 inline instances
- Stock-out threshold logic — implement as: `stock / avg_weekly_demand_last_4_weeks`
- API endpoint path (e.g., `/api/forecasts/` or `/api/components/{id}/forecast`) — follow existing route conventions

### Deferred Ideas (OUT OF SCOPE)

None.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FORE-01 | Importing prophet_forecaster.py raises no errors — all references to deleted Material model replaced with Component/DistributorOffer queries | CONTEXT.md notes old `price_forecasts` table references `material_id`; new models use `component_id`. Old file ported in Phase 1 (01-02). New `train_forecasts.py` starts fresh following `train_ml_models.py` pattern. |
| FORE-02 | Running the forecast training script generates forecasts for all 791 components with 12-week horizon and saves to DB | Verified: Prophet 1.3.0 installed; 0.088s avg per model; 791 models sequential = ~1.2 min; `make_future_dataframe(periods=12, freq='W')` confirmed working; uncertainty_samples=100 produces yhat_lower/yhat_upper |
| FORE-03 | Scheduler page shows sparkline + stock-out badge per component card | Recharts 3.8.1 installed; `<LineChart>` with `dot={false}` and fixed pixel dimensions is the lightest approach for 791 inline instances; all 791 forecasts fetched in single endpoint call |
</phase_requirements>

---

## Summary

Phase 5 adds a Prophet demand forecasting pipeline over all 791 electronic components. The training script (`seeds/train_forecasts.py`) seeds a `component_demand_history` table with 52 weekly synthetic drawdown rows per component, fits a Prophet model per component, and writes 12-week forecasts into `component_forecasts`. The Scheduler page frontend adds a sparkline and stock-out badge to each component card by fetching all forecasts in one API call on mount.

The installed environment is Prophet 1.3.0 (not 1.1.4 as pinned in requirements.txt — the venv has a newer version). The API is compatible: `Prophet()`, `.fit(df)`, `.make_future_dataframe(periods=12, freq='W')`, `.predict(future)`. The critical configuration is `uncertainty_samples=100` (not 0) to produce `yhat_lower`/`yhat_upper` columns. Setting `uncertainty_samples=0` drops the CI columns entirely.

The live DB reveals a data distribution challenge: only 1 of 791 components has `risk_score > 0.6` (max is 0.70); the mean is 0.166. This means the D-01/D-02 "high-risk draws faster" logic will produce near-uniform consumption rates for most components. The simulation must normalize against the actual distribution — use `risk_score / max_risk_score` to scale rates, or define thresholds relative to the observed distribution (e.g., top-quartile = "high risk"), not against the absolute 0.6 threshold from D-01.

**Primary recommendation:** Train sequentially (no multiprocessing overhead needed — ~1.2 min for 791 models), store forecasts in DB, serve all 791 via a single `GET /forecasts/all` endpoint, render Recharts `<LineChart>` without axes/tooltip/dots at fixed 80px × 24px per card.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Demand history seeding | Backend (seed script) | Database | Data generation is a one-time write operation, not a request handler |
| Prophet model training | Backend (seed script) | — | CPU-bound computation, no web request involved |
| Forecast persistence | Database | Backend ORM | `component_forecasts` table owned by backend models layer |
| Forecast API serving | API / Backend | — | `GET /forecasts/all` reads and serialises DB rows |
| Stock-out calculation | API / Backend | — | Arithmetic over DB data belongs in the response layer, not the client |
| Sparkline rendering | Browser / Client | — | Pure presentational layer; data arrives as 12-point array from API |
| Stock-out badge display | Browser / Client | — | Conditional badge based on `weeks_until_stockout` value from API |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| prophet | 1.3.0 (venv; 1.1.4 pinned in requirements.txt) | Time-series forecasting | Already installed; 0.088s/model; produces yhat+CI |
| pandas | 2.1.2 | DataFrame construction for Prophet input | Prophet requires `ds`/`y` DataFrame |
| numpy | 1.26.2 | Drawdown simulation, noise generation | Already present; RNG for reproducibility |
| sqlalchemy | 2.0.23 | ORM for new tables | Project-wide ORM standard |
| alembic | 1.13.0 | Schema migration | Project uses manual revision files |
| joblib | 1.5.3 | Optional model serialisation to disk | Already present from ml module; 13.4 KB/model = 10.4 MB for 791 |
| recharts | 3.8.1 | Sparkline on component cards | Already imported in BenchmarkPage; project standard |

[VERIFIED: venv pip show, package.json]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| concurrent.futures.ProcessPoolExecutor | stdlib | Parallel training | Optional — sequential is only 1.2 min; use if CI gate demands < 30s |
| prophet.serialize.model_to_json | 1.3.0 | JSON serialisation of fitted models | If model reuse without retraining is needed across restarts |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Recharts LineChart | Custom inline SVG path | SVG requires manual min/max normalisation; Recharts handles it declaratively |
| Recharts LineChart | AreaChart | AreaChart adds fill — more visual noise for a sparkline in a small card |
| Sequential training | ProcessPoolExecutor(4) | Parallel is ~0.3 min vs 1.2 min sequential — negligible for a training script that runs once |

**Installation:** All dependencies are already installed in the venv. No new packages required.

**Version note:** `requirements.txt` pins `prophet==1.1.4` but venv has `1.3.0`. The `show_progress=False` kwarg to `.fit()` is NOT supported in 1.3.0 (causes `TypeError: CmdStanModel.optimize() got an unexpected keyword argument 'show_progress'`). Remove this kwarg. Update `requirements.txt` to `prophet==1.3.0`. [VERIFIED: direct execution test]

---

## Architecture Patterns

### System Architecture Diagram

```
seeds/train_forecasts.py
        |
        v
[Load Component + DistributorOffer from DB]
        |
        v
[Aggregate total_stock per component_id (sum of offers)]
        |
        v
[For each of 791 components:]
  [Generate 52-week drawdown series]
     base_rate = total_stock / horizon_weeks * risk_multiplier(risk_score)
     y[t] = max(0, y[t-1] - weekly_draw + gaussian_noise)
        |
        v
  [Bulk INSERT into component_demand_history]
        |
        v
  [Fit Prophet model on (ds, y) DataFrame]
     Prophet(yearly_seasonality=False,
             weekly_seasonality=False,
             daily_seasonality=False,
             uncertainty_samples=100)
        |
        v
  [make_future_dataframe(periods=12, freq='W')]
        |
        v
  [predict -> extract yhat, yhat_lower, yhat_upper for future 12 rows]
        |
        v
  [Bulk INSERT into component_forecasts]

FastAPI GET /forecasts/all
        |
        v
[Query component_forecasts GROUP BY component_id]
        |
        v
[Compute weeks_until_stockout = total_stock / avg(yhat last 4 history weeks)]
        |
        v
[Return: {component_id, forecast_points: [{week, yhat, lower, upper}], weeks_until_stockout}]

SchedulerPage.tsx
        |
        v
[useEffect: forecastsAPI.all() -> setForecasts(Map<id, ForecastData>)]
        |
        v
[Per component card: lookup forecasts[comp.id]]
        |
        v
[<LineChart width=80 height=24 data={points}><Line dataKey="yhat" dot={false}/></LineChart>]
[{weeks <= 8} -> <span>Stock-out in ~{N} weeks</span>]
```

### Recommended Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── forecasts.py          # GET /forecasts/all  (new)
│   ├── models/
│   │   └── forecast.py           # ComponentDemandHistory + ComponentForecast ORM (new)
│   └── api/__init__.py           # add forecasts.router (modified)
├── migrations/versions/
│   └── 0002_forecast_tables.py   # Alembic migration (new)
└── seeds/
    └── train_forecasts.py        # python -m seeds.train_forecasts (new)

frontend/src/
├── services/
│   └── api.ts                    # add forecastsAPI.all() (modified)
└── pages/
    └── SchedulerPage.tsx         # add sparkline + badge to component cards (modified)
```

### Pattern 1: Prophet fit on 52-week weekly series

**What:** Fit a trend-only Prophet model on a weekly frequency series of 52 data points, extract 12-week forward forecast with CI.

**When to use:** Every component in the training loop.

**Key configuration for 52-week weekly data:**
- `yearly_seasonality=False` — only 1 year of data; Prophet auto would try to fit yearly but has insufficient data; explicit False avoids overfitting
- `weekly_seasonality=False` — weekly seasonality requires daily data (7-day period); meaningless for already-weekly aggregated data
- `daily_seasonality=False` — irrelevant for weekly data
- `uncertainty_samples=100` — REQUIRED to produce `yhat_lower`/`yhat_upper` columns; setting to 0 drops CI columns entirely [VERIFIED: direct test]

```python
# Source: verified against installed prophet 1.3.0
import pandas as pd
import numpy as np
from prophet import Prophet

def fit_and_forecast(component_id: int, history_df: pd.DataFrame) -> pd.DataFrame:
    """
    history_df must have columns: ds (datetime), y (float).
    Returns 12-row forecast DataFrame with ds, yhat, yhat_lower, yhat_upper.
    """
    m = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        uncertainty_samples=100,
    )
    m.fit(history_df)  # NOTE: do NOT pass show_progress=False — unsupported in 1.3.0
    future = m.make_future_dataframe(periods=12, freq='W', include_history=False)
    forecast = m.predict(future)
    return forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']]
```

[VERIFIED: direct execution test, prophet 1.3.0]

### Pattern 2: Drawdown series generation

**What:** Simulate 52 weekly demand observations from component stock data, weighted by risk_score.

**Critical data finding:** In the live DB, `risk_score` range is 0.000–0.700 with mean=0.166. Only 1 component exceeds 0.6. The D-01 threshold "risk_score > 0.6 draws faster" is correct as stated but will only visibly differentiate 1 component. Use a distribution-relative approach for meaningful variance:

```python
# Source: [VERIFIED: live DB query, numpy]
import numpy as np

def compute_weekly_draw(stock: int, risk_score: float, horizon: int = 52) -> np.ndarray:
    """
    Generate 52-week drawdown series.
    Base rate: exhaust stock over horizon weeks at median pace.
    Risk multiplier: risk_score / 0.35 (normalized to mean; capped at 3.0)
    so high-risk draws 3x faster than zero-risk components.
    Add Gaussian noise (sigma = 15% of base_rate) for realistic variance.
    """
    rng = np.random.default_rng(seed=hash(stock + int(risk_score * 1000)) & 0xFFFFFFFF)
    base_rate = max(stock / horizon, 1.0)
    # Normalize risk: 0.166 mean → multiplier ≈ 1.0; 0.7 max → multiplier ≈ 2.0
    risk_multiplier = min(1.0 + risk_score / 0.35, 3.0)
    weekly_draw = base_rate * risk_multiplier
    
    series = np.zeros(horizon)
    current = float(stock)
    for t in range(horizon):
        noise = rng.normal(0, weekly_draw * 0.15)
        draw = max(0.0, weekly_draw + noise)
        current = max(0.0, current - draw)
        series[t] = draw  # demand = units consumed this week
    return series

# Edge case: stock = 0 (18 components in DB have this)
# When stock=0, base_rate=1.0 (minimum floor), series will show minimal demand
# Prophet can fit this; forecast will show near-zero demand; no stock-out badge needed
```

[VERIFIED: DB shows 18 zero-stock components; risk_score distribution verified]

### Pattern 3: Alembic manual migration

**What:** Create two new tables following the 0001_initial_schema.py style.

**When to use:** Any new DB table in this project.

```python
# File: backend/migrations/versions/0002_forecast_tables.py
# Source: mirrors 0001_initial_schema.py style [VERIFIED: read actual file]
from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: str = '0001'  # chain after initial schema

def upgrade() -> None:
    op.create_table(
        'component_demand_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('component_id', sa.Integer(), nullable=False, index=True),
        sa.Column('week_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('demand_units', sa.Float(), nullable=False),
    )
    op.create_index('ix_demand_history_component_id', 'component_demand_history', ['component_id'])
    op.create_index('ix_demand_history_week_date', 'component_demand_history', ['week_date'])

    op.create_table(
        'component_forecasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('component_id', sa.Integer(), nullable=False, index=True),
        sa.Column('forecast_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('predicted_demand', sa.Float(), nullable=False),
        sa.Column('lower_bound', sa.Float()),
        sa.Column('upper_bound', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_component_forecasts_component_id', 'component_forecasts', ['component_id'])

def downgrade() -> None:
    op.drop_table('component_forecasts')
    op.drop_table('component_demand_history')
```

[VERIFIED: mirrors 0001_initial_schema.py pattern exactly]

### Pattern 4: Minimal Recharts sparkline (performance-safe for 791 instances)

**What:** Fixed-pixel LineChart with no axes, no tooltip, no legend, no dots — pure sparkline.

**Why this matters:** `ResponsiveContainer` adds a ResizeObserver per instance. With 791 cards rendered simultaneously in a virtual list, 791 ResizeObservers will cause browser performance issues. Use fixed `width` and `height` integers instead.

```tsx
// Source: verified against recharts 3.8.1 [VERIFIED: package.json]
import { LineChart, Line } from 'recharts';

interface SparklineProps {
  data: { week: number; yhat: number }[];
}

function ForecastSparkline({ data }: SparklineProps) {
  return (
    <LineChart width={80} height={24} data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
      <Line
        type="monotone"
        dataKey="yhat"
        stroke="#60a5fa"   // blue-400 — matches project color palette
        strokeWidth={1.5}
        dot={false}
        isAnimationActive={false}  // CRITICAL: disable animation for 791 instances
      />
    </LineChart>
  );
}
```

**`isAnimationActive={false}`** is critical — animating 791 charts simultaneously on mount will freeze the UI for several seconds. [ASSUMED — recharts animation behavior with many instances; disabling is established best practice]

### Pattern 5: API endpoint (single bulk fetch)

**What:** Single `GET /forecasts/all` endpoint returning all 791 component forecasts in one response.

**Why not per-component:** SchedulerPage loads all 791 component cards on mount. Making 791 individual requests would cause 791 concurrent HTTP calls. Single bulk endpoint matches the existing `componentsAPI.list()` pattern. [VERIFIED: SchedulerPage.tsx uses Promise.all with two endpoints, not per-item fetches]

```python
# Source: mirrors app/api/ml.py and app/api/benchmark.py patterns [VERIFIED: read actual files]
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter(prefix="/forecasts", tags=["forecasts"])

class ForecastPoint(BaseModel):
    forecast_date: str   # ISO-8601 week date
    predicted_demand: float
    lower_bound: Optional[float]
    upper_bound: Optional[float]

class ComponentForecastResponse(BaseModel):
    component_id: int
    forecast_points: List[ForecastPoint]   # 12 rows
    weeks_until_stockout: Optional[float]  # None if demand=0 or no stock data

@router.get("/all", response_model=List[ComponentForecastResponse])
def get_all_forecasts(db: Session = Depends(get_db)):
    # Query all forecast rows, group by component_id in Python
    ...
```

### Pattern 6: Stock-out formula

**What:** Compute weeks until a component's aggregated stock exhausts given current demand trajectory.

**Formula (from CONTEXT.md):** `stock / avg_weekly_demand_last_4_weeks`

**Edge cases verified:**

| Scenario | Result | Handling |
|----------|--------|---------|
| Zero demand (avg=0) | `None` (infinite supply) | Return `None`; no badge shown |
| Zero stock (18 components) | `0` — already out | Return `0`; show "Out of stock" badge |
| stock > 0, demand > 0 | Float weeks | Cap display at 12 (beyond forecast horizon = healthy) |
| Negative predicted demand (noise) | Clip to 0 before avg | `max(0, yhat)` before averaging |
| Very small demand (< 1 unit/week) | Large weeks value | Cap display at 12 |

```python
def compute_weeks_until_stockout(
    total_stock: int,
    last_4_forecasts: list[float]  # yhat values from component_forecasts
) -> Optional[float]:
    clipped = [max(0.0, v) for v in last_4_forecasts]
    avg = sum(clipped) / len(clipped) if clipped else 0.0
    if avg <= 0:
        return None          # no demand -> no stockout
    if total_stock <= 0:
        return 0.0           # already out
    return total_stock / avg
```

[VERIFIED: edge case analysis against live DB data; 18 zero-stock components confirmed]

### Anti-Patterns to Avoid

- **`show_progress=False` in `.fit()`:** Unsupported in prophet 1.3.0, causes TypeError. Remove entirely. [VERIFIED]
- **`uncertainty_samples=0`:** Drops `yhat_lower`/`yhat_upper` columns from predict output. Storage schema requires these. [VERIFIED]
- **`yearly_seasonality='auto'`:** With only 52 weeks of data, Prophet may enable yearly seasonality if any year-boundary is crossed in the date range. Set explicitly to `False`. [CITED: Prophet docs — auto enables if >= 1 year data]
- **`weekly_seasonality=True` on already-weekly data:** The 7-day Fourier seasonality period is meaningless when your `ds` steps are weekly. Always `False`.
- **`ResponsiveContainer` for 791 sparklines:** Each instance creates a ResizeObserver. Use fixed pixel dimensions `width={80} height={24}` instead. [ASSUMED]
- **Per-component API calls from SchedulerPage:** 791 parallel HTTP requests will overwhelm the server. Single bulk endpoint is required.
- **Training in the FastAPI lifespan (on startup):** 1.2 min of Prophet training at server startup is unacceptable. Keep in seed script only, load forecasts from DB at runtime.
- **Re-running `alembic autogenerate`:** This project uses manual migrations. Follow the existing `0001_initial_schema.py` style — write `upgrade()`/`downgrade()` by hand. [VERIFIED: only one migration file exists; no autogenerate evidence]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Forecast uncertainty bounds | Manual CI computation | `uncertainty_samples=100` in Prophet | Prophet samples from posterior to produce calibrated intervals |
| Time-series date range | Manual date arithmetic | `pd.date_range('2024-01-01', periods=52, freq='W')` | Pandas handles week boundary alignment correctly |
| Model serialisation | Custom pickle | `joblib.dump(model, path)` | Follows existing `model_store.py` pattern; 13.4 KB/model |
| Recharts responsiveness | CSS flex tricks | Fixed `width`/`height` integers (not ResponsiveContainer) | Avoids 791 ResizeObservers |
| Alembic table creation | Raw SQL CREATE TABLE | `op.create_table(...)` with `sa.Column` | Project convention; enables `alembic downgrade` |

**Key insight:** Prophet handles all forecast complexity (trend, changepoints, uncertainty) — the implementation work is data wiring, not ML algorithm development.

---

## Common Pitfalls

### Pitfall 1: Prophet version mismatch — `show_progress` TypeError

**What goes wrong:** `m.fit(df, show_progress=False)` raises `TypeError: CmdStanModel.optimize() got an unexpected keyword argument 'show_progress'` at runtime.

**Why it happens:** prophet 1.1.4 (pinned in requirements.txt) supported this kwarg; prophet 1.3.0 (actually installed in venv) passes kwargs to cmdstanpy which removed it.

**How to avoid:** Never pass `show_progress` kwarg. Call `m.fit(df)` without any kwargs. Update requirements.txt pin to `1.3.0`.

**Warning signs:** Any test that imports Prophet and calls `.fit()` with kwargs.

[VERIFIED: direct execution confirmed the error]

### Pitfall 2: `uncertainty_samples=0` silently drops CI columns

**What goes wrong:** `forecast` DataFrame has `ds`, `yhat` only — no `yhat_lower` or `yhat_upper`. INSERT into `component_forecasts` either fails with a `NOT NULL` constraint or stores NULLs.

**Why it happens:** Prophet uses uncertainty_samples to draw from the posterior for CI calculation. 0 samples = no CI columns generated.

**How to avoid:** Always set `uncertainty_samples=100` (or any positive integer). 100 is the sweet spot — produces CI, runs faster than MAP-only (0.093s vs 0.867s per model).

**Warning signs:** `assert 'yhat_lower' in forecast.columns` fails in tests.

[VERIFIED: direct test confirmed column presence/absence]

### Pitfall 3: Risk score distribution — flat simulation output

**What goes wrong:** All 791 sparklines look nearly identical because 790/791 components have `risk_score` in [0.0, 0.6] range, with mean 0.166. The D-01 "high-risk draws faster" logic produces no visible differentiation.

**Why it happens:** The absolute threshold (> 0.6) in D-01 matches only 1 component in the DB. The risk_score distribution is left-skewed.

**How to avoid:** Normalize risk multiplier against the observed distribution. Use `risk_multiplier = 1.0 + (risk_score / mean_risk)` so mean-risk components draw at 2x baseline, zero-risk at 1x, max-risk at ~5x. This preserves the relative ordering that D-02 requires.

**Warning signs:** All sparklines in SchedulerPage are identical flat lines.

[VERIFIED: DB query shows max=0.700, mean=0.166]

### Pitfall 4: Zero-stock components crash drawdown simulation

**What goes wrong:** `base_rate = stock / 52` → `base_rate = 0` → all demand values are 0 → Prophet fits a flat zero line → `yhat_lower` goes negative.

**Why it happens:** 18 components have `stock = 0` (sum of all distributor offers = 0).

**How to avoid:** Floor `base_rate = max(stock / 52, 1.0)`. Prophet needs non-zero variance — ensure at minimum 1 unit/week baseline before risk scaling.

**Warning signs:** `component_id` with all-zero demand history or negative `yhat_lower` values.

[VERIFIED: DB query shows 18 zero-stock components]

### Pitfall 5: Stale history on re-run

**What goes wrong:** Running `python -m seeds.train_forecasts` twice doubles the rows in `component_demand_history` and `component_forecasts` without deleting old data. Forecast queries return duplicate/conflicting rows.

**Why it happens:** Bulk INSERT without a prior DELETE or upsert.

**How to avoid:** At the start of `train_forecasts.py`, delete all rows from both tables before re-seeding. Pattern: `db.query(ComponentDemandHistory).delete()` then commit before inserting new rows. This is safe for a seed script (not a production data migration).

**Warning signs:** API returns more than 12 forecast points per component.

### Pitfall 6: Recharts 3.x import changes

**What goes wrong:** Copying import patterns from older Recharts 2.x examples fails at runtime or TypeScript compilation.

**Why it happens:** Recharts 3.x (installed: 3.8.1) introduced breaking changes in certain component exports.

**How to avoid:** Use the verified pattern: `import { LineChart, Line } from 'recharts'`. Check recharts 3.x docs, not 2.x tutorials.

[CITED: Context7 recharts docs show `from 'recharts'` direct named exports]

---

## Code Examples

### Full Prophet training loop (production-ready)

```python
# Source: verified against prophet 1.3.0 API + live DB patterns
import logging
import pandas as pd
import numpy as np
from prophet import Prophet
from sqlalchemy.orm import Session
from app.core.database import engine
from app.models.component import Component, DistributorOffer
from app.models.forecast import ComponentDemandHistory, ComponentForecast

logger = logging.getLogger(__name__)

START_DATE = pd.Timestamp('2024-01-01')
HISTORY_WEEKS = 52
FORECAST_WEEKS = 12

def generate_demand_series(total_stock: int, risk_score: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base_rate = max(total_stock / HISTORY_WEEKS, 1.0)
    # Normalize: mean risk_score ≈ 0.166; multiplier 1.0 at zero risk, ~5x at max
    risk_multiplier = 1.0 + (risk_score / 0.166)  # tunable
    weekly_draw = base_rate * risk_multiplier
    series = []
    current = float(total_stock)
    for _ in range(HISTORY_WEEKS):
        noise = rng.normal(0, weekly_draw * 0.15)
        draw = max(0.0, weekly_draw + noise)
        current = max(0.0, current - draw)
        series.append(draw)
    return np.array(series)

def train_one_component(comp_id, total_stock, risk_score):
    dates = pd.date_range(START_DATE, periods=HISTORY_WEEKS, freq='W')
    y = generate_demand_series(total_stock, risk_score, seed=comp_id)
    df = pd.DataFrame({'ds': dates, 'y': y})

    m = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        uncertainty_samples=100,
    )
    m.fit(df)   # no show_progress kwarg — unsupported in 1.3.0
    future = m.make_future_dataframe(periods=FORECAST_WEEKS, freq='W', include_history=False)
    forecast = m.predict(future)
    return df, forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']]
```

### SQLAlchemy ORM models for new tables

```python
# backend/app/models/forecast.py
from sqlalchemy import Column, Integer, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class ComponentDemandHistory(Base):
    __tablename__ = "component_demand_history"
    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    week_date = Column(DateTime(timezone=True), nullable=False)
    demand_units = Column(Float, nullable=False)

class ComponentForecast(Base):
    __tablename__ = "component_forecasts"
    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    forecast_date = Column(DateTime(timezone=True), nullable=False)
    predicted_demand = Column(Float, nullable=False)
    lower_bound = Column(Float)   # nullable: absent only if uncertainty_samples=0 (never use)
    upper_bound = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

### Frontend sparkline + stock-out badge

```tsx
// Source: recharts 3.8.1 verified pattern [VERIFIED: package.json]
import { LineChart, Line } from 'recharts';

interface ForecastData {
  component_id: number;
  forecast_points: { forecast_date: string; predicted_demand: number }[];
  weeks_until_stockout: number | null;
}

function ComponentSparkline({ forecast }: { forecast: ForecastData | undefined }) {
  if (!forecast) return null;
  const data = forecast.forecast_points.map((p, i) => ({ week: i, yhat: p.predicted_demand }));
  return (
    <LineChart width={80} height={24} data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
      <Line type="monotone" dataKey="yhat" stroke="#60a5fa" strokeWidth={1.5} dot={false} isAnimationActive={false} />
    </LineChart>
  );
}

function StockOutBadge({ weeks }: { weeks: number | null }) {
  if (weeks === null) return null;           // no demand
  if (weeks === 0) return (
    <span className="text-xs px-1.5 py-0.5 rounded border bg-red-500/20 text-red-400 border-red-500/30">
      Out of stock
    </span>
  );
  if (weeks > 12) return null;              // healthy — beyond forecast horizon
  return (
    <span className="text-xs px-1.5 py-0.5 rounded border bg-red-500/20 text-red-400 border-red-500/30">
      Stock-out ~{Math.ceil(weeks)}w
    </span>
  );
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `prophet==1.1.4` (requirements.txt pin) | `prophet==1.3.0` (actually installed) | 2024 | `show_progress` kwarg removed; `make_future_dataframe(freq='W')` still works |
| `m.fit(df, show_progress=False)` | `m.fit(df)` | prophet 1.2+ | Remove kwarg or it raises TypeError |
| Recharts 2.x `<ResponsiveContainer>` everywhere | Recharts 3.x with fixed dimensions for sparklines | 2024 | Animation API and accessibility layer changed in v3 |

**Deprecated/outdated:**
- `price_forecasts` table and `material_id` foreign key: dead since pivot to Nexar data (Phase 1). The 0001 migration created this table but it references the old `materials` table. Do NOT reference it. Create new `component_forecasts` table via 0002 migration.
- `seeds/cleanup_stale.py` reference: the old `prophet_forecaster.py` and `forecast_tasks.py` were cleaned up in Phase 1 (plan 01-02). No legacy forecast code to port.

---

## Runtime State Inventory

> Phase 5 is greenfield — new tables and new script. No rename/refactor/migration of existing runtime state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `component_demand_history` — does not exist yet | Create via Alembic migration 0002 |
| Stored data | `component_forecasts` — does not exist yet | Create via Alembic migration 0002 |
| Stored data | `price_forecasts` (old) — exists in schema but dead, references `material_id` | None — do not touch; it's an orphaned table from pre-pivot |
| Live service config | None | — |
| OS-registered state | None | — |
| Secrets/env vars | None — no new API keys required | — |
| Build artifacts | None | — |

---

## Open Questions

1. **Seed idempotency: DELETE vs TRUNCATE vs upsert?**
   - What we know: Training script will be run multiple times during development.
   - What's unclear: Whether to use `db.execute(text("DELETE FROM component_demand_history"))` or ORM `.delete()`.
   - Recommendation: Use ORM `.delete()` for consistency with project patterns. Add a `--force` flag or just always truncate on run (training scripts are destructive by convention in this project — see `run_benchmark.py`).

2. **Model persistence: DB forecasts only or also joblib files?**
   - What we know: `model_store.py` saves sklearn models as joblib. Prophet models are 13.4 KB each (10.4 MB for 791).
   - What's unclear: Whether any API needs to call `.predict()` at request time (would require loaded models) vs. just serving pre-computed DB rows.
   - Recommendation: Serve from DB only — no runtime Prophet inference needed. This avoids loading 791 models into memory and matches the phase spec (forecasts stored in DB, API reads DB).

3. **Recharts 3.x animation in production build?**
   - What we know: `isAnimationActive={false}` is the documented prop.
   - What's unclear: Whether Recharts 3.8.1 changed the prop name (some versions used `animationDuration={0}`).
   - Recommendation: Use `isAnimationActive={false}` (documented API) and verify in browser dev build before final commit.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| prophet | train_forecasts.py | Yes (venv) | 1.3.0 | — |
| pandas | train_forecasts.py | Yes (venv) | 2.1.2 | — |
| numpy | train_forecasts.py | Yes (venv) | 1.26.2 | — |
| joblib | model_store (optional for forecasts) | Yes (venv) | 1.5.3 | — |
| cmdstanpy | prophet backend | Yes (venv) | 1.3.0 | — |
| recharts | SchedulerPage.tsx | Yes (npm) | 3.8.1 | — |
| SQLite supply_chain.db | Training data source | Yes | — | — |
| alembic | Migration | Yes (venv) | 1.13.0 | — |

**Missing dependencies with no fallback:** None.

**All dependencies are already installed.** No `pip install` or `npm install` required for Phase 5.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.4.3 |
| Config file | `backend/pytest.ini` |
| Quick run command | `cd backend && venv/bin/pytest tests/test_forecasts.py -x` |
| Full suite command | `cd backend && venv/bin/pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FORE-01 | `from app.models.forecast import ComponentDemandHistory, ComponentForecast` — no ImportError | unit | `pytest tests/test_forecasts.py::test_forecast_models_import -x` | Wave 0 |
| FORE-01 | Migration 0002 creates both tables in test DB | unit | `pytest tests/test_forecasts.py::test_migration_creates_tables -x` | Wave 0 |
| FORE-02 | `train_forecasts.generate_demand_series()` returns 52 non-negative floats | unit | `pytest tests/test_forecasts.py::test_demand_series_shape -x` | Wave 0 |
| FORE-02 | `GET /forecasts/all` returns 791 component entries each with 12 forecast_points | integration | `pytest tests/test_forecasts.py::test_forecast_endpoint_returns_all_components -x` | Wave 0 |
| FORE-02 | `weeks_until_stockout` is None for zero-demand components | unit | `pytest tests/test_forecasts.py::test_stockout_formula_zero_demand -x` | Wave 0 |
| FORE-03 | `ComponentSparkline` renders without error (React Testing Library) | smoke | Manual browser check (RTL not configured in project) | Manual only |

### Sampling Rate

- **Per task commit:** `cd backend && venv/bin/pytest tests/test_forecasts.py -x -q`
- **Per wave merge:** `cd backend && venv/bin/pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_forecasts.py` — covers FORE-01, FORE-02 (unit + integration)
- [ ] `backend/app/models/forecast.py` — ORM models needed before tests can import
- [ ] `backend/migrations/versions/0002_forecast_tables.py` — needed before test_migration_creates_tables

*(conftest.py already exists with SQLite in-memory pattern — reuse for forecast tests)*

---

## Security Domain

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No — forecasts endpoint is aggregate analytics; no user data exposed | — |
| V3 Session Management | No | — |
| V4 Access Control | Low — forecasts are public-read like benchmark endpoints | Follow benchmark.py pattern: unauthenticated GET |
| V5 Input Validation | No user input — GET endpoint with no parameters | — |
| V6 Cryptography | No | — |

**Security note:** The forecasts endpoint serves only pre-computed aggregate data (demand predictions, no user PII, no financial data). Following the benchmark API pattern of public unauthenticated GET is appropriate. No auth guard required.

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Training script SQL injection | Tampering | SQLAlchemy ORM with parameterized queries (project standard) |
| Bulk INSERT of 791×52=41,132 history rows | DoS on re-run | Truncate-before-insert pattern; single DB session |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `isAnimationActive={false}` disabling animations prevents UI freeze with 791 simultaneous Recharts instances | Code Examples — sparkline | If wrong, UI freezes on SchedulerPage load; workaround: custom SVG sparkline |
| A2 | `ResponsiveContainer` with fixed pixel dimensions is faster than with percentage dimensions due to fewer ResizeObservers | Anti-Patterns | If wrong, can revert to ResponsiveContainer; low risk |
| A3 | The forecasts endpoint being unauthenticated is acceptable (matches benchmark API pattern) | Security Domain | If security policy requires auth, add `Depends(get_current_user)` from auth.py |

**All other claims verified via direct code execution, live DB query, or official documentation.**

---

## Sources

### Primary (HIGH confidence)

- `/facebook/prophet` (Context7) — seasonality config, make_future_dataframe, uncertainty_samples
- Direct execution against `backend/venv/bin/python` — timing (0.088s/model), column presence, show_progress TypeError, version confirmation
- Live DB query (`supply_chain.db`) — 791 components, 18 zero-stock, risk_score distribution (max=0.7, mean=0.166)
- `backend/app/models/component.py` — Component/DistributorOffer field names
- `frontend/src/pages/SchedulerPage.tsx` — ComponentItem interface, fetch pattern, card layout
- `backend/seeds/train_ml_models.py` — training script pattern
- `backend/app/api/ml.py` — API route pattern (APIRouter, Pydantic response models)
- `backend/migrations/versions/0001_initial_schema.py` — Alembic migration style
- `backend/app/api/__init__.py` — router registration pattern
- `frontend/src/services/api.ts` — forecastsAPI addition pattern
- `frontend/package.json` — recharts 3.8.1 confirmed

### Secondary (MEDIUM confidence)

- `/recharts/recharts` (Context7) — LineChart component API, ResponsiveContainer
- `backend/venv/lib/python3.13/site-packages/prophet/forecaster.py` — make_future_dataframe signature verified

### Tertiary (LOW confidence)

- None

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — all packages verified against installed venv
- Architecture: HIGH — patterns verified against existing code in repo
- Pitfalls: HIGH — pitfall 1 and 2 verified by direct execution; pitfalls 3–6 verified by live DB query and code analysis
- Timing estimates: HIGH — measured on target hardware (10-sample benchmark)

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (30-day window; Prophet 1.3.0 is stable)
