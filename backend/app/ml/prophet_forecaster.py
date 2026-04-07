"""
Prophet-based price forecasting for tech manufacturing materials.

Usage:
    forecaster = ProphetForecaster(db)
    forecaster.train_and_store(material_id)  # trains + writes PriceForecast rows

Falls back gracefully if prophet is not installed.
"""
import logging
import os
import pickle
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "models")
os.makedirs(MODEL_DIR, exist_ok=True)


class ProphetForecaster:
    def __init__(self, db):
        self.db = db

    def _load_history(self, material_id: int):
        """Return list of (date, price) tuples from price_history."""
        from app.models.material import PriceHistory
        rows = (
            self.db.query(PriceHistory)
            .filter(PriceHistory.material_id == material_id)
            .order_by(PriceHistory.date)
            .all()
        )
        return [(r.date, r.price) for r in rows if r.price]

    def train_and_store(self, material_id: int, horizon_days: int = 90) -> bool:
        """Train a Prophet model and write PriceForecast rows to DB.

        Returns True on success, False if not enough data or prophet unavailable.
        """
        from app.models.material import PriceForecast, Material

        history = self._load_history(material_id)
        if len(history) < 30:
            logger.warning(f"Material {material_id}: insufficient history ({len(history)} rows)")
            return False

        try:
            import pandas as pd
            from prophet import Prophet

            df = pd.DataFrame(history, columns=["ds", "y"])
            df["ds"] = pd.to_datetime(df["ds"])
            df = df.sort_values("ds").drop_duplicates("ds")

            model = Prophet(
                interval_width=0.80,
                changepoint_prior_scale=0.05,
                seasonality_mode="multiplicative",
                yearly_seasonality=True,
                weekly_seasonality=False,
                daily_seasonality=False,
            )
            model.fit(df)

            # Serialize model to disk
            mat = self.db.query(Material).filter(Material.id == material_id).first()
            model_path = os.path.join(MODEL_DIR, f"prophet_material_{material_id}.pkl")
            with open(model_path, "wb") as f:
                pickle.dump(model, f)

            # Generate forecast
            future = model.make_future_dataframe(periods=horizon_days)
            forecast = model.predict(future)
            fc_rows = forecast.tail(horizon_days)

            # Delete old forecasts
            self.db.query(PriceForecast).filter(PriceForecast.material_id == material_id).delete()

            for _, row in fc_rows.iterrows():
                self.db.add(PriceForecast(
                    material_id=material_id,
                    forecast_date=row["ds"].to_pydatetime(),
                    predicted_price=max(0, row["yhat"]),
                    lower_ci=max(0, row["yhat_lower"]),
                    upper_ci=max(0, row["yhat_upper"]),
                    model_version="prophet_v1",
                ))
            self.db.commit()
            logger.info(f"Trained Prophet model for material {material_id} ({len(fc_rows)} forecast rows)")
            return True

        except ImportError:
            logger.warning("prophet / pandas not installed — using linear fallback")
            return self._linear_fallback(material_id, history, horizon_days)
        except Exception as e:
            logger.error(f"Prophet training failed for material {material_id}: {e}")
            return False

    def _linear_fallback(self, material_id: int, history, horizon_days: int) -> bool:
        """Simple linear trend extrapolation when prophet is unavailable."""
        from app.models.material import PriceForecast

        prices = [p for _, p in history]
        avg = sum(prices[-30:]) / min(30, len(prices))
        recent_trend = (prices[-1] - prices[-30]) / 30 if len(prices) >= 30 else 0

        self.db.query(PriceForecast).filter(PriceForecast.material_id == material_id).delete()
        for i in range(1, horizon_days + 1):
            pred = max(avg * 0.01, avg + recent_trend * i)
            ci = pred * 0.05 * (i / horizon_days + 0.5)
            self.db.add(PriceForecast(
                material_id=material_id,
                forecast_date=datetime.utcnow() + timedelta(days=i),
                predicted_price=round(pred, 4),
                lower_ci=round(pred - ci, 4),
                upper_ci=round(pred + ci, 4),
                model_version="linear_fallback_v1",
            ))
        self.db.commit()
        return True


def load_model(material_id: int):
    """Load a serialized Prophet model from disk."""
    model_path = os.path.join(MODEL_DIR, f"prophet_material_{material_id}.pkl")
    if not os.path.exists(model_path):
        return None
    with open(model_path, "rb") as f:
        return pickle.load(f)
