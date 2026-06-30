"""
Champion selection over already-logged MLflow runs (P5).

Re-evaluates the runs in an experiment and promotes the lowest-RMSE model to
``champion`` in the MLflow Model Registry — without retraining. Useful after
several training runs have accumulated.

Usage:
    cd backend
    python -m seeds.select_champion                 # both experiments
    python -m seeds.select_champion lead_time       # lead-time models only
    python -m seeds.select_champion forecast        # prophet forecast only
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from app.ml.mlflow_tracking import (
        FORECAST_EXPERIMENT,
        FORECAST_MODEL,
        LEAD_TIME_EXPERIMENT,
        LEAD_TIME_MODEL,
        get_tracking_uri,
        select_champion,
    )

    which = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    targets = []
    if which in ("all", "lead_time", "leadtime"):
        targets.append((LEAD_TIME_EXPERIMENT, LEAD_TIME_MODEL))
    if which in ("all", "forecast", "prophet"):
        targets.append((FORECAST_EXPERIMENT, FORECAST_MODEL))
    if not targets:
        logger.error("unknown target %r — use 'lead_time', 'forecast', or 'all'", which)
        sys.exit(1)

    logger.info("Tracking store: %s", get_tracking_uri())
    any_ok = False
    for experiment, model_name in targets:
        try:
            champ = select_champion(experiment, model_name, metric="rmse")
            logger.info(
                "%-18s champion=%s RMSE=%.3f -> %s v%s [alias=%s]",
                experiment, champ["model_name"], champ["value"],
                champ["registered_model"], champ["version"], champ["alias"],
            )
            any_ok = True
        except ValueError as exc:
            logger.warning("%-18s skipped: %s", experiment, exc)

    if not any_ok:
        logger.error("No champion selected — have you run training with MLflow enabled?")
        sys.exit(1)


if __name__ == "__main__":
    main()
