"""
Serve-time model resolution — MLflow champion first, on-disk joblib fallback.

Why this module exists
----------------------
Training (``seeds/train_ml_models.py``) logs every lead-time model to MLflow,
picks the lowest-RMSE run and points the ``champion`` alias at it
(``app/ml/mlflow_tracking.select_champion``). Before this module existed the API
NEVER consulted that alias: startup just ``joblib.load``-ed
``backend/data/ml_models/lead_time.joblib`` and served whatever the
``metrics.joblib`` blob happened to name as "best". The registry was decorative.

What happens now, in order:

  1. **MLflow registry** — if a tracking/registry store is reachable, resolve
     ``models:/lead_time_predictor@champion``, load that exact model version and
     serve it. Provenance (version, run id, source run, selection metric) is
     recorded.
  2. **On-disk joblib fallback** — if there is no registry (this is the *normal*
     case on the Render free tier: no MLflow server, no ``mlruns/mlflow.db`` in
     the image), serve ``data/ml_models/lead_time.joblib``, which is committed on
     purpose for exactly this reason.

The fallback is real, not decorative: the deployed instance runs on it. So the
provenance is surfaced honestly — ``model_source`` is ``mlflow_registry`` or
``local_joblib``, never a fiction — via ``GET /api/v1/ml/model-info``, on the
``/ml/lead-time`` prediction response, and in the startup log line.

Env knobs:
  * ``MLFLOW_TRACKING_URI``  — point at a remote/other store; if set, the registry
    path is attempted.
  * ``MLFLOW_SERVING=off``   — skip the registry entirely and go straight to disk
    (useful on the deploy image to avoid a pointless probe on every boot).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.ml import MLState, model_store
from app.ml.mlflow_tracking import CHAMPION_ALIAS, DEFAULT_DB, LEAD_TIME_MODEL

logger = logging.getLogger(__name__)

SOURCE_MLFLOW = "mlflow_registry"
SOURCE_JOBLIB = "local_joblib"
SOURCE_NONE = "none"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _serving_enabled() -> bool:
    """False when MLFLOW_SERVING is explicitly disabled (deploy image)."""
    return os.environ.get("MLFLOW_SERVING", "auto").lower() not in ("0", "off", "false", "no")


def registry_reachable() -> Tuple[bool, str]:
    """Cheap pre-check: is there any MLflow store worth talking to?

    Returns ``(reachable, reason_if_not)``. We do NOT want a 30s socket timeout on
    every Render cold boot, so an unset ``MLFLOW_TRACKING_URI`` + a missing local
    ``mlruns/mlflow.db`` short-circuits to "no registry" immediately.
    """
    if not _serving_enabled():
        return False, "MLFLOW_SERVING=off (registry lookup disabled by env)"
    if os.environ.get("MLFLOW_TRACKING_URI"):
        return True, ""
    if DEFAULT_DB.exists():
        return True, ""
    return False, (
        f"no MLflow store: MLFLOW_TRACKING_URI unset and {DEFAULT_DB} does not exist "
        "(expected on the Render free tier — no MLflow server is deployed)"
    )


def resolve_lead_time_champion() -> Tuple[Optional[Any], Dict[str, Any]]:
    """Load ``lead_time_predictor@champion`` from the MLflow registry.

    Returns ``(model, provenance)`` on success, or ``(None, {"fallback_reason": ...})``
    when no registry / no champion alias / load failure. Never raises.
    """
    ok, why = registry_reachable()
    if not ok:
        return None, {"fallback_reason": why}

    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        from app.ml.mlflow_tracking import get_tracking_uri

        uri = get_tracking_uri()
        mlflow.set_tracking_uri(uri)
        mlflow.set_registry_uri(uri)
        client = MlflowClient()

        mv = client.get_model_version_by_alias(LEAD_TIME_MODEL, CHAMPION_ALIAS)
        model_uri = f"models:/{LEAD_TIME_MODEL}@{CHAMPION_ALIAS}"
        model = mlflow.sklearn.load_model(model_uri)

        run_model_name: Optional[str] = None
        try:
            run = client.get_run(mv.run_id)
            run_model_name = run.data.tags.get("model_name") or run.data.params.get("model_name")
        except Exception:  # noqa: BLE001 — provenance nicety, not load-bearing
            pass

        prov = {
            "model_source": SOURCE_MLFLOW,
            "registered_model": LEAD_TIME_MODEL,
            "model_version": str(mv.version),
            "alias": CHAMPION_ALIAS,
            "run_id": mv.run_id,
            "model_uri": model_uri,
            "tracking_uri": uri,
            "model_name": run_model_name,
            "selection_metric": (mv.tags or {}).get("selection_metric"),
            "selection_value": (mv.tags or {}).get("selection_value"),
            "resolved_at": _now(),
            "fallback_reason": None,
        }
        logger.info(
            "serving lead-time model from MLflow registry: %s v%s [@%s] run=%s (%s)",
            LEAD_TIME_MODEL, mv.version, CHAMPION_ALIAS, mv.run_id, run_model_name,
        )
        return model, prov
    except Exception as exc:  # noqa: BLE001 — any registry failure => honest fallback
        return None, {"fallback_reason": f"{type(exc).__name__}: {exc}"}


def _artifact_provenance(best_name: Optional[str], fallback_reason: Optional[str]) -> Dict[str, Any]:
    path: Path = model_store.path("lead_time")
    mtime = None
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    return {
        "model_source": SOURCE_JOBLIB,
        "registered_model": None,
        "model_version": None,
        "alias": None,
        "run_id": None,
        "model_uri": str(path),
        "tracking_uri": None,
        "model_name": best_name,
        "selection_metric": "rmse",
        "selection_value": None,
        "artifact_mtime": mtime,
        "resolved_at": _now(),
        "fallback_reason": fallback_reason,
    }


def load_ml_state() -> Optional[MLState]:
    """Build the serving :class:`MLState` — champion if resolvable, else disk.

    Returns ``None`` when no models are present at all (fresh checkout that never
    ran training); callers already treat that as "ML disabled".
    """
    if not model_store.models_exist():
        logger.warning("no ML artifacts on disk — ML endpoints will report 503")
        return None

    regime_pipe = model_store.load("regime")
    regime_features = model_store.load("regime_features")
    lt_models = model_store.load("lead_time") or {}
    feature_cols = model_store.load("feature_cols") or []
    metrics = model_store.load("metrics") or {}

    best = metrics.get("best_lead_time_model")
    if not best and lt_models:
        best = min(lt_models, key=lambda k: lt_models[k].get("rmse", float("inf")))
    stress = metrics.get("current_stress_prob", 0.0)

    champion, prov = resolve_lead_time_champion()
    if champion is not None:
        serving_model = champion
        # The registry knows which of the 4 estimators won; prefer its label.
        if prov.get("model_name") in lt_models:
            best = prov["model_name"]
        else:
            prov["model_name"] = prov.get("model_name") or best
    else:
        reason = prov.get("fallback_reason")
        serving_model = lt_models.get(best, {}).get("model") if best else None
        prov = _artifact_provenance(best, reason)
        logger.info(
            "serving lead-time model from on-disk artifact %s (model=%s) — MLflow champion "
            "not used: %s",
            prov["model_uri"], best, reason,
        )

    prov["n_training_samples"] = metrics.get("n_training_samples")
    prov["n_features"] = metrics.get("n_features") or (len(feature_cols) or None)

    return MLState(
        regime_model=regime_pipe,
        regime_features=regime_features,
        lead_time_models=lt_models,
        best_lead_time_model=best,
        current_stress_prob=stress,
        feature_columns=feature_cols,
        serving_model=serving_model,
        provenance=prov,
    )


def get_serving_model(state: Optional[MLState]) -> Optional[Any]:
    """The single estimator that actually answers predictions for ``state``."""
    if state is None:
        return None
    if getattr(state, "serving_model", None) is not None:
        return state.serving_model
    if state.lead_time_models and state.best_lead_time_model:
        info = state.lead_time_models.get(state.best_lead_time_model)
        if info:
            return info.get("model")
    return None


def model_source(state: Optional[MLState]) -> str:
    """``mlflow_registry`` | ``local_joblib`` | ``none`` — what served the answer."""
    if state is None or not getattr(state, "provenance", None):
        return SOURCE_NONE
    return state.provenance.get("model_source", SOURCE_NONE)
