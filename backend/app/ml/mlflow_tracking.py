"""
MLflow experiment tracking + model registry (P5).

Wraps the existing training/evaluation pipeline in MLflow so every model fit is
reproducible and comparable:

  * Lead-time models (Ridge / RandomForest / GradientBoosting / MLP) — one nested
    run each under a parent "lead_time_training" run. Logs hyperparameters, the
    holdout RMSE / MAE / R2 computed by ``lead_time_model.train_all_models`` (the
    REAL backtest numbers — nothing is fabricated here), and the fitted estimator
    as an artifact.
  * Prophet demand forecast — one run logging the seasonality config + horizon,
    the WAPE / RMSE / bias / MAPE from the real rolling-origin backtest in
    ``run_forecast_backtest`` (FRED IPG3344S), and the fitted Prophet model.

Champion selection (:func:`select_champion`) queries the logged runs for an
experiment, picks the one with the lowest RMSE, registers that run's model in the
MLflow Model Registry, and points the ``champion`` alias at the new version.

Storage is local and infra-free. By default everything goes to a local SQLite
tracking + registry store under ``backend/mlruns/mlflow.db`` (MLflow 3 put the
bare filesystem store in maintenance mode, so SQLite is the supported local
backend). Override with the ``MLFLOW_TRACKING_URI`` env var.

View the UI with:
    mlflow ui --backend-store-uri sqlite:///backend/mlruns/mlflow.db
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# backend/app/ml/mlflow_tracking.py -> parents[2] == backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = BACKEND_ROOT / "mlruns" / "mlflow.db"

LEAD_TIME_EXPERIMENT = "lead_time_models"
FORECAST_EXPERIMENT = "demand_forecast"
LEAD_TIME_MODEL = "lead_time_predictor"
FORECAST_MODEL = "prophet_demand_forecast"
CHAMPION_ALIAS = "champion"


# ── store configuration ───────────────────────────────────────────────────────

def get_tracking_uri() -> str:
    """Return the tracking/registry URI.

    Honors ``MLFLOW_TRACKING_URI`` if set (lets tests/CI point at a tmp dir);
    otherwise defaults to a local SQLite store under ``backend/mlruns/``.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if uri:
        return uri
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_DB}"


def configure_mlflow(experiment_name: str) -> str:
    """Point MLflow at the local store and select/create the experiment."""
    import mlflow

    uri = get_tracking_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    mlflow.set_experiment(experiment_name)
    return uri


# ── helpers ────────────────────────────────────────────────────────────────────

def _underlying_estimator(model: Any) -> Any:
    """Unwrap a sklearn Pipeline (scaler + model) to the inner estimator."""
    steps = getattr(model, "named_steps", None)
    if steps and "model" in steps:
        return steps["model"]
    return model


def _hyperparams(model: Any) -> Dict[str, Any]:
    """Extract loggable (scalar) hyperparameters from a fitted estimator."""
    est = _underlying_estimator(model)
    try:
        params = est.get_params(deep=False)
    except Exception:  # not a sklearn estimator
        return {}
    out: Dict[str, Any] = {}
    for key, val in params.items():
        if isinstance(val, bool) or val is None or isinstance(val, (int, float, str)):
            out[f"hp_{key}"] = val
        elif isinstance(val, (tuple, list)):
            out[f"hp_{key}"] = str(val)
    return out


def _is_loggable_metric(val: Any) -> bool:
    return isinstance(val, (int, float)) and not (isinstance(val, float) and math.isnan(val))


# ── lead-time models ─────────────────────────────────────────────────────────

def log_lead_time_models(
    results: Dict[str, Dict],
    *,
    n_samples: int,
    n_features: int,
    extra_params: Optional[Dict[str, Any]] = None,
    register_champion: bool = True,
) -> Dict[str, Any]:
    """Log the 4 lead-time models to MLflow and (optionally) select a champion.

    Args:
        results: output of ``lead_time_model.train_all_models`` —
            ``{name: {"model": fitted, "rmse": .., "mae": .., "r2": ..}}``.
            The metrics are the REAL holdout numbers; they are logged as-is.
        n_samples / n_features: shape of the training matrix (for the parent run).
        extra_params: extra params to log on the parent run (e.g. data source).
        register_champion: if True, run champion selection after logging.

    Returns:
        ``{"run_ids": {name: run_id}, "champion": <select_champion result|None>}``.
    """
    import mlflow
    import mlflow.sklearn

    configure_mlflow(LEAD_TIME_EXPERIMENT)
    run_ids: Dict[str, str] = {}

    with mlflow.start_run(run_name="lead_time_training"):
        mlflow.log_param("n_samples", n_samples)
        mlflow.log_param("n_features", n_features)
        mlflow.log_param("test_split", 0.2)
        mlflow.log_param("n_models", len(results))
        for key, val in (extra_params or {}).items():
            mlflow.log_param(key, val)

        for name, info in results.items():
            with mlflow.start_run(run_name=name, nested=True) as run:
                model = info["model"]
                mlflow.set_tag("model_name", name)
                mlflow.log_param("model_name", name)
                mlflow.log_param("estimator", type(_underlying_estimator(model)).__name__)
                for hkey, hval in _hyperparams(model).items():
                    mlflow.log_param(hkey, hval)

                mlflow.log_metric("rmse", float(info["rmse"]))
                mlflow.log_metric("mae", float(info["mae"]))
                mlflow.log_metric("r2", float(info["r2"]))

                try:
                    model_info = mlflow.sklearn.log_model(model, name="model")
                    mlflow.set_tag("model_uri", model_info.model_uri)
                except Exception as exc:  # pragma: no cover - artifact best-effort
                    logger.warning("could not log model artifact for %s: %s", name, exc)

                run_ids[name] = run.info.run_id

    champion = None
    if register_champion:
        champion = select_champion(LEAD_TIME_EXPERIMENT, LEAD_TIME_MODEL, metric="rmse")
    return {"run_ids": run_ids, "champion": champion}


# ── prophet demand forecast ───────────────────────────────────────────────────

def log_prophet_backtest(
    *,
    params: Dict[str, Any],
    metrics: Dict[str, Any],
    model: Any = None,
    register: bool = True,
) -> Dict[str, Any]:
    """Log a Prophet demand-forecast run from the real rolling-origin backtest.

    Args:
        params: seasonality config, horizon, n_windows, series id, etc.
        metrics: real backtest metrics (wape/rmse/bias/mape/skill ...). NaN/None
            values are skipped, never invented.
        model: an optional fitted Prophet model to log as the run artifact.
        register: if True, register + champion-alias the lowest-RMSE forecast run.
    """
    import mlflow

    configure_mlflow(FORECAST_EXPERIMENT)
    with mlflow.start_run(run_name="prophet_backtest") as run:
        for key, val in params.items():
            mlflow.log_param(key, val)
        for key, val in metrics.items():
            if _is_loggable_metric(val):
                mlflow.log_metric(key, float(val))

        if model is not None:
            try:
                import mlflow.prophet

                model_info = mlflow.prophet.log_model(model, name="model")
                mlflow.set_tag("model_uri", model_info.model_uri)
            except Exception as exc:  # pragma: no cover - artifact best-effort
                logger.warning("could not log prophet artifact: %s", exc)

        run_id = run.info.run_id

    champion = None
    if register:
        champion = select_champion(FORECAST_EXPERIMENT, FORECAST_MODEL, metric="rmse")
    return {"run_id": run_id, "champion": champion}


# ── champion selection / registry ─────────────────────────────────────────────

def select_champion(
    experiment_name: str,
    registered_model_name: str,
    *,
    metric: str = "rmse",
    maximize: bool = False,
) -> Dict[str, Any]:
    """Register the best run's model and point the ``champion`` alias at it.

    Queries every run in ``experiment_name`` that logged ``metric``, picks the
    best (lowest by default), registers that run's logged model in the registry,
    and sets the ``champion`` alias + provenance tags on the new version.
    """
    import mlflow
    from mlflow.tracking import MlflowClient

    configure_mlflow(experiment_name)
    client = MlflowClient()

    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        raise ValueError(f"experiment {experiment_name!r} not found")

    runs = client.search_runs([exp.experiment_id], max_results=1000)
    scored = [r for r in runs if metric in r.data.metrics]
    if not scored:
        raise ValueError(f"no runs in {experiment_name!r} logged metric {metric!r}")

    chooser = max if maximize else min
    best = chooser(scored, key=lambda r: r.data.metrics[metric])

    model_uri = best.data.tags.get("model_uri") or f"runs:/{best.info.run_id}/model"
    mv = mlflow.register_model(model_uri, registered_model_name)

    client.set_registered_model_alias(registered_model_name, CHAMPION_ALIAS, mv.version)
    client.set_model_version_tag(registered_model_name, mv.version, "selection_metric", metric)
    client.set_model_version_tag(
        registered_model_name, mv.version, "selection_value", f"{best.data.metrics[metric]:.6f}"
    )
    client.set_model_version_tag(registered_model_name, mv.version, "source_run_id", best.info.run_id)

    model_name = best.data.tags.get("model_name") or best.data.params.get("model_name")
    logger.info(
        "champion for %s: %s (run=%s) %s=%.4f -> registered %s v%s",
        experiment_name, model_name, best.info.run_id, metric,
        best.data.metrics[metric], registered_model_name, mv.version,
    )
    return {
        "registered_model": registered_model_name,
        "version": mv.version,
        "alias": CHAMPION_ALIAS,
        "run_id": best.info.run_id,
        "model_name": model_name,
        "metric": metric,
        "value": float(best.data.metrics[metric]),
    }
