"""
Prophet demand forecasting training script (Phase 5, FORE-02).

Usage:
    cd backend
    python -m seeds.train_forecasts

Pipeline:
  1. Truncate component_demand_history and component_forecasts (idempotency — Pitfall 5).
  2. For each of 791 components:
       a. Sum DistributorOffer.stock to get total_stock.
       b. Generate a 52-week risk-weighted drawdown series (Pattern 2).
          - base_rate = max(total_stock / 52, 1.0)        # zero-stock floor (Pitfall 4)
          - risk_multiplier = min(1.0 + risk_score / 0.166, 5.0)   # mean-normalised (Pitfall 3)
          - weekly_draw = base_rate * risk_multiplier + Gaussian noise (sigma = 15% of weekly_draw)
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
NOISE_FRACTION = 0.15              # sigma = 15% of weekly_draw
PROGRESS_LOG_EVERY = 50            # log every Nth component


def generate_demand_series(total_stock: int, risk_score: float, seed: int):
    """
    Generate 52 weekly demand observations for one component.

    Args:
        total_stock: SUM(DistributorOffer.stock) for the component (>= 0).
        risk_score: Component.risk_score in [0.0, 1.0] (live DB range: 0.0–0.700, mean 0.166).
        seed: Per-component seed (component_id is a good choice — keeps reproducibility per component).

    Returns:
        numpy.ndarray of shape (HISTORY_WEEKS=52,), all values >= 0.

    Critical edge cases (verified against live DB):
      - total_stock=0 (18 components): base_rate floored at 1.0 to avoid degenerate Prophet input (Pitfall 4).
      - risk_score=0.0: risk_multiplier=1.0 (baseline drawdown).
      - risk_score=0.700 (max in DB): risk_multiplier ≈ 5.0 (capped) — visibly faster drawdown.
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    base_rate = max(total_stock / HISTORY_WEEKS, 1.0)
    risk_multiplier = min(1.0 + (risk_score / RISK_SCORE_NORMALIZER), RISK_MULTIPLIER_CAP)
    weekly_draw = base_rate * risk_multiplier
    series = np.zeros(HISTORY_WEEKS)
    for t in range(HISTORY_WEEKS):
        noise = rng.normal(0.0, weekly_draw * NOISE_FRACTION)
        series[t] = max(0.0, weekly_draw + noise)
    return series


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

        # 3. Date axis (shared across all components — same 52-week calendar)
        history_dates = pd.date_range(START_DATE, periods=HISTORY_WEEKS, freq="W")

        history_payload: List[dict] = []
        forecast_payload: List[dict] = []

        for i, comp in enumerate(components, start=1):
            total_stock = stock_by_component.get(comp.id, 0)
            risk_score = float(comp.risk_score or 0.0)

            # 3a. Generate drawdown
            y = generate_demand_series(total_stock, risk_score, seed=comp.id)

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
