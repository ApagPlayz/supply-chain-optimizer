"""
Prophet demand forecasting training script (Phase 5, FORE-02).

Usage:
    cd backend
    python -m seeds.train_forecasts

HONESTY NOTE (read before trusting these numbers):
  Only the temporal SHAPE of each series is real. The per-part MAGNITUDE is an
  ILLUSTRATIVE scaling by inventory position and risk — it is NOT observed
  per-part demand. No public per-SKU demand series exists for electronic
  components (documented in docs/ROUTE_A_BUILD_PLAN.md), so this seed exists to
  populate a plausible demand *curve* for the UI/optimizer, not to make accuracy
  claims. The credible, defensible demand numbers live in the two REAL backtests:
    - macro:   seeds/run_forecast_backtest.py  (Census M3 New Orders, A34SNO)
    - per-SKU: seeds/run_carparts_backtest.py  (Monash Car Parts, 2,674 series)

Pipeline:
  1. Truncate component_demand_history and component_forecasts (idempotency — Pitfall 5).
  The 52-week temporal shape comes from FRED "Manufacturers' New Orders: Computers
  & Electronic Products" (Census M3 series A34SNO — the real *demand* target, $M,
  monthly, 1992->present), fetched keyless via the public fredgraph CSV endpoint
  and cached in seeds/data/. So trend is a genuine macro demand signal; the
  per-part level applied on top of it is an illustrative scaling only.

  2. For each of 791 components:
       a. Sum DistributorOffer.stock to get total_stock.
       b. Build a 52-week demand series: real A34SNO shape x an illustrative level.
          - base_rate = max(total_stock / 52, 1.0)        # zero-stock floor (Pitfall 4)
          - risk_multiplier = min(1.0 + risk_score / 0.166, 5.0)   # mean-normalised (Pitfall 3)
          - weekly[t] = base_rate * risk_multiplier * index_shape[t]  (index mean == 1.0)
          NOTE: base_rate * risk_multiplier is the ILLUSTRATIVE magnitude, not observed.
       c. Bulk INSERT 52 rows into component_demand_history.
       d. Fit Prophet on (ds, y) with uncertainty_samples=100 (NOT 0 — Pitfall 2)
          and NO show_progress kwarg (Pitfall 1).
       e. predict() the 12-week future (freq='W', include_history=False).
       f. Bulk INSERT 12 rows into component_forecasts (yhat / yhat_lower / yhat_upper).
  3. Final commit. Log row counts.

Runtime: ~1.2 min sequential for 791 components.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# sys.path bootstrap — mirrors seeds/run_benchmark.py
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Configuration constants (do not change without coordinating with /forecasts/all consumer in 05-03)
START_DATE = datetime(2024, 1, 7, tzinfo=timezone.utc)   # first Sunday of 2024 — matches pd.date_range freq='W' alignment
HISTORY_WEEKS = 52
FORECAST_WEEKS = 12
RISK_SCORE_NORMALIZER = 0.166      # observed mean across 791 components (RESEARCH.md DB query)
RISK_MULTIPLIER_CAP = 5.0          # max-risk component draws ~5x baseline
PROGRESS_LOG_EVERY = 50            # log every Nth component
# Census M3 "Manufacturers' New Orders: Computers & Electronic Products" ($M, monthly,
# 1992->now) — the real macro *demand* target, served keyless via the FRED CSV endpoint.
FRED_DEMAND_SERIES = "A34SNO"
CACHE_PATH = Path(__file__).resolve().parent / "data" / "a34sno_monthly.csv"


def load_demand_index_shape(weeks: int = HISTORY_WEEKS, refresh: bool = True):
    """
    Return a real `weeks`-length unit-mean demand shape from Census M3 A34SNO.

    Resolution order (real-data-only — we never fabricate the shape):
      1. If refresh, try the keyless fredgraph CSV endpoint and refresh the cache.
      2. Otherwise / on network failure, load the cached snapshot in seeds/data/.
      3. If neither is available, raise — the caller must not proceed with fake data.
    """
    import numpy as np  # noqa: F401  (kept for symmetry / explicit dep)
    import pandas as pd

    from app.ml.fred_client import build_weekly_demand_shape, fetch_fred_series_csv

    series = None
    if refresh:
        series = fetch_fred_series_csv(FRED_DEMAND_SERIES, start="2010-01-01")
        if series is not None:
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                series.to_frame().to_csv(CACHE_PATH, index_label="observation_date")
                logger.info("Refreshed FRED %s cache (%d obs) at %s", FRED_DEMAND_SERIES, len(series), CACHE_PATH)
            except Exception as exc:  # caching is best-effort
                logger.warning("Could not write FRED cache: %s", exc)

    if series is None:
        if not CACHE_PATH.exists():
            raise FileNotFoundError(
                f"No FRED {FRED_DEMAND_SERIES} data: live fetch failed and no cache at {CACHE_PATH}. "
                "Run once with network access to populate the cache."
            )
        df = pd.read_csv(CACHE_PATH, parse_dates=["observation_date"], index_col="observation_date")
        series = df.iloc[:, 0]
        logger.info("Loaded FRED %s from cache (%d obs)", FRED_DEMAND_SERIES, len(series))

    return build_weekly_demand_shape(series, weeks=weeks)


def generate_demand_series(total_stock: int, risk_score: float, index_shape):
    """
    Build 52 weekly demand observations for one component.

    HONEST SCOPING: the temporal SHAPE (`index_shape`) is real — a unit-mean
    trajectory derived from the Census M3 A34SNO new-orders series. The LEVEL it
    is scaled to (base_rate * risk_multiplier) is an ILLUSTRATIVE proxy from
    inventory position and risk, NOT observed per-part demand (no such public
    series exists for electronic components). There is no random noise: all
    temporal variation is the genuine macro demand signal; only the magnitude
    is a modelled stand-in.

    Args:
        total_stock: SUM(DistributorOffer.stock) for the component (>= 0).
        risk_score: Component.risk_score in [0.0, 1.0] (live DB range: 0.0–0.700, mean 0.166).
        index_shape: length-52 unit-mean array from load_demand_index_shape().

    Returns:
        numpy.ndarray of shape (HISTORY_WEEKS=52,), all values >= 0.

    Critical edge cases (verified against live DB):
      - total_stock=0 (18 components): base_rate floored at 1.0 to avoid degenerate Prophet input (Pitfall 4).
      - risk_score=0.0: risk_multiplier=1.0 (baseline level).
      - risk_score=0.700 (max in DB): risk_multiplier ≈ 5.0 (capped) — visibly higher demand.
    """
    import numpy as np
    shape = np.asarray(index_shape, dtype=float)
    if shape.shape[0] != HISTORY_WEEKS:
        raise ValueError(f"index_shape must have {HISTORY_WEEKS} points, got {shape.shape[0]}")
    base_rate = max(total_stock / HISTORY_WEEKS, 1.0)
    risk_multiplier = min(1.0 + (risk_score / RISK_SCORE_NORMALIZER), RISK_MULTIPLIER_CAP)
    weekly_draw = base_rate * risk_multiplier
    return np.maximum(0.0, weekly_draw * shape)


def main() -> None:
    """Train Prophet for all 791 components and write forecasts to DB."""
    import numpy as np
    import pandas as pd
    from prophet import Prophet
    from sqlalchemy import func as sqla_func
    from sqlalchemy.orm import Session

    from app.core.database import engine
    from app.models.component import Component, DistributorOffer
    from app.models.forecast import ComponentDemandHistory, ComponentForecast

    # Silence prophet/cmdstanpy noise — they emit one INFO line per fit which would flood logs for 791 components.
    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    with Session(engine) as db:
        # 1. Truncate (idempotency — Pitfall 5)
        deleted_h = db.query(ComponentDemandHistory).delete()
        deleted_f = db.query(ComponentForecast).delete()
        db.commit()
        logger.info("Cleared %d demand_history rows and %d forecast rows from previous runs", deleted_h, deleted_f)

        # 2. Aggregate stock per component (single GROUP BY query)
        stock_rows = (
            db.query(
                DistributorOffer.component_id,
                sqla_func.coalesce(sqla_func.sum(DistributorOffer.stock), 0).label("total_stock"),
            )
            .group_by(DistributorOffer.component_id)
            .all()
        )
        stock_by_component = {row.component_id: int(row.total_stock or 0) for row in stock_rows}

        components = db.query(Component).order_by(Component.id).all()
        if not components:
            logger.error("No Component rows in DB — run `python -m seeds.seed_db` first")
            sys.exit(1)
        logger.info("Training Prophet on %d components (sequential, ~1.2 min expected)", len(components))

        # Real demand SHAPE from Census M3 A34SNO — loaded once, shared across components.
        # (magnitude applied per component below is illustrative, not observed.)
        index_shape = load_demand_index_shape(weeks=HISTORY_WEEKS, refresh=True)

        # 3. Date axis (shared across all components — same 52-week calendar)
        history_dates = pd.date_range(START_DATE, periods=HISTORY_WEEKS, freq="W")

        history_payload: List[dict] = []
        forecast_payload: List[dict] = []

        for i, comp in enumerate(components, start=1):
            total_stock = stock_by_component.get(comp.id, 0)
            risk_score = float(comp.risk_score or 0.0)

            # 3a. Build demand: real A34SNO shape x illustrative per-component level
            y = generate_demand_series(total_stock, risk_score, index_shape)

            # 3b. Stage history rows
            for week_idx, week_date in enumerate(history_dates):
                history_payload.append({
                    "component_id": comp.id,
                    "week_date": week_date.to_pydatetime().replace(tzinfo=timezone.utc),
                    "demand_units": float(y[week_idx]),
                })

            # 3c. Fit Prophet — NO show_progress kwarg (Pitfall 1), uncertainty_samples=100 (Pitfall 2)
            df = pd.DataFrame({"ds": history_dates.tz_localize(None), "y": y})
            m = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=False,
                daily_seasonality=False,
                uncertainty_samples=100,
            )
            m.fit(df)

            future = m.make_future_dataframe(periods=FORECAST_WEEKS, freq="W", include_history=False)
            forecast = m.predict(future)

            # 3d. Stage forecast rows
            for _, row in forecast.iterrows():
                forecast_payload.append({
                    "component_id": comp.id,
                    "forecast_date": row["ds"].to_pydatetime().replace(tzinfo=timezone.utc),
                    "predicted_demand": float(row["yhat"]),
                    "lower_bound": float(row["yhat_lower"]) if "yhat_lower" in row else None,
                    "upper_bound": float(row["yhat_upper"]) if "yhat_upper" in row else None,
                })

            if i % PROGRESS_LOG_EVERY == 0 or i == len(components):
                logger.info("Trained %d/%d components", i, len(components))

        # 4. Bulk INSERT — single commit at end (faster than per-component commits)
        logger.info("Writing %d history rows and %d forecast rows...", len(history_payload), len(forecast_payload))
        db.bulk_insert_mappings(ComponentDemandHistory, history_payload)
        db.bulk_insert_mappings(ComponentForecast, forecast_payload)
        db.commit()

        # 5. Sanity-check counts
        n_hist = db.query(ComponentDemandHistory).count()
        n_fcst = db.query(ComponentForecast).count()
        logger.info("DONE — component_demand_history=%d, component_forecasts=%d", n_hist, n_fcst)
        if n_fcst != len(components) * FORECAST_WEEKS:
            logger.error(
                "Row count mismatch: expected %d forecast rows (%d components × %d weeks), got %d",
                len(components) * FORECAST_WEEKS, len(components), FORECAST_WEEKS, n_fcst,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
