"""
Champion selection over already-logged MLflow runs (P5).

Re-evaluates the runs in an experiment and promotes the best model to
``champion`` in the MLflow Model Registry — without retraining. Useful after
several training runs have accumulated.

SELECTION METRIC. Lead-time models are ranked on ``cv_rmse_mean`` — the mean
RMSE over repeated FAMILY-GROUPED splits — which is the same metric
``retrain_lead_time`` and ``log_lead_time_models`` use. This script used to rank
on the single-split score instead, so running it promoted a DIFFERENT model
than the training pipeline had evaluated and chosen (on the current panel:
Ridge by single-split RMSE, gradient boosting by grouped CV). One metric, one
champion; the constant is defined in app/ml/mlflow_tracking.

COMPARABLE RUNS ONLY. Lead-time runs are ranked strictly within ONE data panel,
identified by the SHA-256 of ``observed_lead_times.csv``. ``cv_rmse_mean`` is an
absolute error in days on whatever rows a run saw, so it does not compare across
vintages: when the weekly collector grew the panel 1,879 -> 2,615 rows, the new
run scored 69.03 and the superseded run 68.80, and ranking them together pointed
the ``champion`` alias at a 263-feature estimator that could not consume a
324-feature matrix at all. If NOTHING has been trained on the panel currently on
disk, this script promotes nothing and says so — the committed
``data/ml_models/lead_time.joblib`` keeps serving, so refusing costs nothing.

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


def current_panel_sha() -> str:
    """SHA-256 of the lead-time panel in THIS checkout — the comparability key.

    Exits rather than falling back to an unfiltered ranking: without a panel
    there is no way to tell comparable runs from incomparable ones, and an
    unfiltered ranking is precisely the defect this filter exists to stop.
    """
    from app.ml.lead_time_collector import PANEL_PATH
    from app.ml.model_store import file_sha256, repo_relative

    sha = file_sha256(PANEL_PATH) if PANEL_PATH.exists() else None
    if not sha:
        logger.error(
            "cannot hash the lead-time panel at %s — champion selection would have "
            "to rank runs from unknown data vintages against each other, which is "
            "meaningless. Refusing.", repo_relative(PANEL_PATH),
        )
        sys.exit(1)
    return sha


def main() -> None:
    from app.ml.mlflow_tracking import (
        FORECAST_EXPERIMENT,
        FORECAST_MODEL,
        FORECAST_SELECTION_METRIC,
        LEAD_TIME_EXPERIMENT,
        LEAD_TIME_MODEL,
        LEAD_TIME_SELECTION_METRIC,
        get_tracking_uri,
        select_champion,
    )

    which = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    targets = []
    if which in ("all", "lead_time", "leadtime"):
        targets.append((
            LEAD_TIME_EXPERIMENT, LEAD_TIME_MODEL, LEAD_TIME_SELECTION_METRIC,
            current_panel_sha(),
        ))
    if which in ("all", "forecast", "prophet"):
        # No panel file: the forecast is fitted on a live FRED series, so there
        # is nothing to hash and nothing to restrict on.
        targets.append((FORECAST_EXPERIMENT, FORECAST_MODEL, FORECAST_SELECTION_METRIC, None))
    if not targets:
        logger.error("unknown target %r — use 'lead_time', 'forecast', or 'all'", which)
        sys.exit(1)

    logger.info("Tracking store: %s", get_tracking_uri())
    any_ok = False
    for experiment, model_name, metric, data_sha in targets:
        if data_sha:
            logger.info("%-18s comparable-run filter: panel %s", experiment, data_sha[:12])
        try:
            champ = select_champion(
                experiment, model_name, metric=metric, require_data_sha=data_sha,
            )
            logger.info(
                "%-18s champion=%s %s=%.3f (of %d comparable run(s)) -> %s v%s [alias=%s]",
                experiment, champ["model_name"], metric, champ["value"],
                champ["n_comparable_runs"], champ["registered_model"],
                champ["version"], champ["alias"],
            )
            any_ok = True
        except ValueError as exc:
            logger.warning("%-18s promoted NOTHING: %s", experiment, exc)

    if not any_ok:
        logger.error(
            "No champion promoted. Either nothing has been trained with MLflow "
            "enabled, or every logged run belongs to a superseded data vintage — "
            "the warning above says which. This is not an outage: serving falls "
            "back to the committed data/ml_models/lead_time.joblib."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
