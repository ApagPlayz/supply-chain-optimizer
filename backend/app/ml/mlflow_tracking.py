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
experiment, picks the one with the lowest RMSE **among the runs trained on the
same data panel**, registers that run's model in the MLflow Model Registry, and
points the ``champion`` alias at the new version. The panel restriction is not
optional bookkeeping: the metric is an absolute error in days on whatever rows a
run saw, so ranking across vintages is meaningless — see
:data:`TRAINING_DATA_SHA_PARAM`.

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
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ml import model_store

logger = logging.getLogger(__name__)

# backend/app/ml/mlflow_tracking.py -> parents[2] == backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = BACKEND_ROOT / "mlruns" / "mlflow.db"

LEAD_TIME_EXPERIMENT = "lead_time_models"
FORECAST_EXPERIMENT = "demand_forecast"
LEAD_TIME_MODEL = "lead_time_predictor"
FORECAST_MODEL = "prophet_demand_forecast"
CHAMPION_ALIAS = "champion"

#: THE selection metric for each registered model. Defined once so the training
#: pipeline and `seeds/select_champion.py` cannot rank on different things and
#: promote different winners — which is exactly what happened when this script
#: ranked lead-time runs on single-split `rmse` while training chose on
#: `cv_rmse_mean`. Lead time is selected on the mean RMSE over repeated
#: FAMILY-GROUPED splits, because an ungrouped or single-split number scores
#: memorisation of a part family.
LEAD_TIME_SELECTION_METRIC = "cv_rmse_mean"
FORECAST_SELECTION_METRIC = "rmse"

#: Run params recording WHICH training panel a run actually saw. Every lead-time
#: run stamps these, and champion selection compares runs ONLY within one panel.
#:
#: WHY THIS EXISTS. ``cv_rmse_mean`` is an absolute error **in days, on whatever
#: rows that run was given**. It is not a normalised score and it is not
#: comparable across data vintages. Ranking every historical run together
#: therefore compares numbers measured on different populations, and on
#: 2026-09-03 that promoted the WRONG model: the weekly collector grew the panel
#: from 1,879 usable rows / 263 features to 2,615 / 324, the new run scored
#: cv_rmse_mean 69.03 and the OLD run scored 68.80, so the old run "won" and the
#: ``champion`` alias was pointed at a 263-feature estimator. Every serve-time
#: call then raised ``X has 324 features, but GradientBoostingRegressor is
#: expecting 263``. A lower number on an easier panel is not a better model.
#:
#: The panel identity is the SHA-256 of the panel file, computed with
#: :func:`app.ml.model_store.file_sha256` — the same hash ``metrics.joblib``
#: provenance records and the same one the staleness tripwire compares, so there
#: is exactly one notion of "which panel" in this codebase.
TRAINING_DATA_SHA_PARAM = "training_data_sha256"
TRAINING_DATA_PATH_PARAM = "training_data_path"


class IncomparableRunsError(ValueError):
    """No logged run was trained on the panel that is currently on disk.

    Raised instead of promoting a run from a different data vintage. It is a
    ``ValueError`` so existing callers (``seeds/select_champion.py``) keep
    handling it, but it is nameable so a caller can tell "nothing comparable"
    apart from "nothing logged at all".
    """


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


def training_data_params(training_data_path: Optional[Path]) -> Dict[str, str]:
    """The panel-identity params every run must carry, or ``{}`` if unknowable.

    Returns an empty dict when no path is given or the file cannot be hashed —
    a run that cannot prove which panel it saw records nothing rather than
    recording a guess, and champion selection then treats it as incomparable.
    """
    if training_data_path is None:
        return {}
    sha = model_store.file_sha256(Path(training_data_path))
    if not sha:
        logger.warning(
            "could not hash training data %s — this run will record no panel "
            "identity and cannot be selected as champion", training_data_path,
        )
        return {}
    return {
        TRAINING_DATA_SHA_PARAM: sha,
        TRAINING_DATA_PATH_PARAM: model_store.repo_relative(Path(training_data_path)),
    }


# ── lead-time models ─────────────────────────────────────────────────────────

def log_lead_time_models(
    results: Dict[str, Dict],
    *,
    n_samples: int,
    n_features: int,
    training_data_path: Optional[Path] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    register_champion: bool = True,
) -> Dict[str, Any]:
    """Log the 4 lead-time models to MLflow and (optionally) select a champion.

    Args:
        results: output of ``lead_time_model.train_all_models`` —
            ``{name: {"model": fitted, "rmse": .., "mae": .., "r2": ..}}``.
            The metrics are the REAL holdout numbers; they are logged as-is.
        n_samples / n_features: shape of the training matrix (for the parent run).
        training_data_path: the panel these models were fitted on. Its SHA-256 is
            stamped on the parent AND on every nested run
            (:data:`TRAINING_DATA_SHA_PARAM`) and is what restricts champion
            selection to comparable runs. Omitting it means the runs record no
            panel identity and can never win a filtered selection — deliberate:
            an unknown vintage is not a comparable one.
        extra_params: extra params to log on the parent run (e.g. data source).
        register_champion: if True, run champion selection after logging.

    Returns:
        ``{"run_ids": {name: run_id}, "champion": <select_champion result|None>}``.
    """
    import mlflow
    import mlflow.sklearn

    configure_mlflow(LEAD_TIME_EXPERIMENT)
    run_ids: Dict[str, str] = {}
    data_params = training_data_params(training_data_path)

    with mlflow.start_run(run_name="lead_time_training"):
        mlflow.log_param("n_samples", n_samples)
        mlflow.log_param("n_features", n_features)
        mlflow.log_param("test_split", 0.2)
        mlflow.log_param("n_models", len(results))
        for key, val in data_params.items():
            mlflow.log_param(key, val)
        for key, val in (extra_params or {}).items():
            mlflow.log_param(key, val)

        for name, info in results.items():
            with mlflow.start_run(run_name=name, nested=True) as run:
                model = info["model"]
                mlflow.set_tag("model_name", name)
                mlflow.log_param("model_name", name)
                mlflow.log_param("estimator", type(_underlying_estimator(model)).__name__)
                # The nested run is what champion selection ranks, so the panel
                # identity has to live on IT — inheriting it from the parent is
                # not a thing MLflow does, and a filter that reads the child's
                # params would silently match nothing.
                for key, val in data_params.items():
                    mlflow.log_param(key, val)
                for hkey, hval in _hyperparams(model).items():
                    mlflow.log_param(hkey, hval)

                mlflow.log_metric("rmse", float(info["rmse"]))
                mlflow.log_metric("mae", float(info["mae"]))
                mlflow.log_metric("r2", float(info["r2"]))
                # Repeated-split CV (n=75 makes a single 15-point split noise).
                # cv_rmse_mean is the metric the champion is actually chosen on.
                for cv_key in ("cv_rmse_mean", "cv_rmse_std", "cv_r2_mean", "cv_r2_std"):
                    if cv_key in info:
                        mlflow.log_metric(cv_key, float(info[cv_key]))

                try:
                    model_info = mlflow.sklearn.log_model(model, name="model")
                    mlflow.set_tag("model_uri", model_info.model_uri)
                except Exception as exc:  # pragma: no cover - artifact best-effort
                    logger.warning("could not log model artifact for %s: %s", name, exc)

                run_ids[name] = run.info.run_id

    champion = None
    if register_champion:
        # Select on mean CV RMSE — the same criterion retrain_lead_time uses for
        # `best`, so the registry champion and the on-disk `best` agree — and
        # ONLY among the runs that saw this same panel.
        champion = select_champion(
            LEAD_TIME_EXPERIMENT,
            LEAD_TIME_MODEL,
            metric=LEAD_TIME_SELECTION_METRIC,
            require_data_sha=data_params.get(TRAINING_DATA_SHA_PARAM),
        )
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
        champion = select_champion(
            FORECAST_EXPERIMENT, FORECAST_MODEL, metric=FORECAST_SELECTION_METRIC
        )
    return {"run_id": run_id, "champion": champion}


# ── champion selection / registry ─────────────────────────────────────────────

def _panel_summary(runs: List[Any]) -> str:
    """``sha -> count`` over a run list, for an error a human can act on."""
    counts = Counter(
        sha[:12] if (sha := r.data.params.get(TRAINING_DATA_SHA_PARAM)) else "<no panel recorded>"
        for r in runs
    )
    return ", ".join(f"{sha} x{n}" for sha, n in sorted(counts.items()))


def select_champion(
    experiment_name: str,
    registered_model_name: str,
    *,
    metric: str = "rmse",
    maximize: bool = False,
    require_data_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Register the best run's model and point the ``champion`` alias at it.

    Queries every run in ``experiment_name`` that logged ``metric``, picks the
    best (lowest by default), registers that run's logged model in the registry,
    and sets the ``champion`` alias + provenance tags on the new version.

    ``require_data_sha`` RESTRICTS THE FIELD TO COMPARABLE RUNS. When given, only
    runs whose :data:`TRAINING_DATA_SHA_PARAM` equals it are ranked — because the
    selection metric is an absolute error measured on whatever rows a run saw, so
    a run trained on a different (or unrecorded) panel is not on the same scale
    and cannot be ranked against one that is. See :data:`TRAINING_DATA_SHA_PARAM`
    for the incident this prevents.

    Behaviour by number of matching runs:
      * **none**  — raise :class:`IncomparableRunsError`. Promoting the best of a
        set of incomparable runs is exactly the defect; refusing is the correct
        answer, and the existing on-disk joblib (``app/ml/serving.py``) keeps
        serving, so nothing goes down. The alias is left untouched: a champion
        for a panel nobody has retrained on is stale, and ``serving.py`` refuses
        it on its feature width rather than this function guessing.
      * **one**   — it wins by default (there is nothing to rank it against), but
        it still has to have logged ``metric`` to get here.
      * **many**  — ranked among themselves on ``metric``, exactly as before.

    Passing ``None`` (the default) disables the filter — used by the demand
    forecast, which is fitted on a live FRED series rather than a committed
    panel file, so there is no file to hash.
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

    if require_data_sha:
        comparable = [
            r for r in scored
            if r.data.params.get(TRAINING_DATA_SHA_PARAM) == require_data_sha
        ]
        if not comparable:
            raise IncomparableRunsError(
                f"no run in {experiment_name!r} was trained on the panel currently "
                f"on disk (sha {require_data_sha[:12]}). {len(scored)} run(s) logged "
                f"{metric!r}, on these panels: {_panel_summary(scored)}. REFUSING to "
                f"promote any of them: {metric!r} is an absolute error measured on "
                "whatever rows a run saw, so it cannot rank runs across data "
                "vintages — ranking them together is how a 263-feature estimator "
                "became the champion for a 324-feature panel. Retrain with "
                "`python -m seeds.train_ml_models` to log a run on this panel; until "
                "then the committed data/ml_models/lead_time.joblib keeps serving."
            )
        logger.info(
            "champion field restricted to the %d/%d run(s) trained on panel %s",
            len(comparable), len(scored), require_data_sha[:12],
        )
        scored = comparable

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
    best_sha = best.data.params.get(TRAINING_DATA_SHA_PARAM)
    if best_sha:
        # WHICH PANEL this champion was measured on travels with the version, so
        # `selection_value` can never be read as comparable to another version's.
        client.set_model_version_tag(
            registered_model_name, mv.version, TRAINING_DATA_SHA_PARAM, best_sha
        )

    model_name = best.data.tags.get("model_name") or best.data.params.get("model_name")
    logger.info(
        "champion for %s: %s (run=%s) %s=%.4f on panel %s -> registered %s v%s",
        experiment_name, model_name, best.info.run_id, metric,
        best.data.metrics[metric], (best_sha or "<unrecorded>")[:12],
        registered_model_name, mv.version,
    )
    return {
        "registered_model": registered_model_name,
        "version": mv.version,
        "alias": CHAMPION_ALIAS,
        "run_id": best.info.run_id,
        "model_name": model_name,
        "metric": metric,
        "value": float(best.data.metrics[metric]),
        "training_data_sha256": best_sha,
        "n_comparable_runs": len(scored),
    }
