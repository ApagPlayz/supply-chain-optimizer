"""
Celery tasks for training Prophet forecasting models.
Runs weekly (Sunday 02:00 UTC) to refresh all material forecasts.
"""
import logging
from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ml.train_all_forecasts")
def train_all_forecasts():
    """Train Prophet models for every material with ≥30 price history rows."""
    from app.core.database import SessionLocal
    from app.models.material import Material
    from app.ml.prophet_forecaster import ProphetForecaster

    db = SessionLocal()
    success, failed = 0, 0
    try:
        materials = db.query(Material).all()
        forecaster = ProphetForecaster(db)
        for mat in materials:
            ok = forecaster.train_and_store(mat.id)
            if ok:
                success += 1
            else:
                failed += 1
    finally:
        db.close()
    return {"trained": success, "failed": failed}


@celery_app.task(name="ml.train_forecast_for_material")
def train_forecast_for_material(material_id: int):
    """Train/refresh forecast for a single material on-demand."""
    from app.core.database import SessionLocal
    from app.ml.prophet_forecaster import ProphetForecaster

    db = SessionLocal()
    try:
        forecaster = ProphetForecaster(db)
        return forecaster.train_and_store(material_id)
    finally:
        db.close()
