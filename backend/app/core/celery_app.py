from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "logistics",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.scrapers.data_pipeline", "app.ml.forecast_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # Pull FRED + Alpha Vantage prices every day at 06:00 UTC
        "daily-price-pull": {
            "task": "pipeline.run_full_pipeline",
            "schedule": crontab(hour=6, minute=0),
        },
        # Retrain Prophet models every Sunday at 02:00 UTC
        "weekly-forecast-retrain": {
            "task": "ml.train_all_forecasts",
            "schedule": crontab(hour=2, minute=0, day_of_week=0),
        },
    },
)
