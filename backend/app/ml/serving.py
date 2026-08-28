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


def _derive_model_version(artifact_provenance: Optional[Dict[str, Any]]) -> Optional[str]:
    """A short, human-meaningful version string for the on-disk joblib.

    The artifact carries no version counter (there is no registry on this path),
    but ``model_store.build_provenance`` DOES stamp fit-time provenance into
    ``metrics.joblib["provenance"]`` — ``git_sha`` and ``trained_at``. Prefer the
    short git sha (what actually distinguishes one committed artifact from the
    next); fall back to the training date if no sha was recorded. Never invent a
    number — if neither is present, there is no version to report.
    """
    prov = artifact_provenance or {}
    git_sha = prov.get("git_sha")
    if git_sha:
        sha, _, dirty = str(git_sha).partition("-")
        short = sha[:7]
        return f"{short}-{dirty}" if dirty else short
    trained_at = prov.get("trained_at")
    if trained_at:
        # ISO timestamp -> just the date part, e.g. "2026-08-17".
        return str(trained_at).split("T", 1)[0]
    return None


def _artifact_provenance(
    best_name: Optional[str],
    fallback_reason: Optional[str],
    artifact_provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    path: Path = model_store.path("lead_time")
    mtime = None
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    return {
        "model_source": SOURCE_JOBLIB,
        "registered_model": None,
        "model_version": _derive_model_version(artifact_provenance),
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


def resolve_regime_signal(metrics: Dict[str, Any]) -> Tuple[Any, Any, float, Dict[str, Any]]:
    """Resolve the macro-stress signal HONESTLY. Returns (pipe, features, prob, status).

    Why this function exists
    -----------------------
    The old code read ``current_stress_prob`` straight out of ``metrics.joblib``
    — a scalar baked at training time (0.9967, 2026-07-10) — and
    ``app/optimization/sourcing.py`` priced a stock-out risk premium off it. A
    months-old constant was posing as live model output. That scalar is never
    read again.

    Now there are exactly three outcomes, and all three are labelled:

      1. ``model``            — the regime pipeline loaded AND passed its ship
         gate, so ``P(stress)`` is recomputed here from the persisted feature
         frame. **This is the normal production path**: ``regime.joblib`` and
         ``regime_features.joblib`` ARE git-tracked (``.gitignore`` un-ignores
         both with ``!``), so they ship in the image and this branch is what the
         deployed service takes.
      2. ``unavailable_no_artifact`` — no regime pipeline on disk. Falls back to
         the documented default ``REGIME_UNAVAILABLE_STRESS_PROB = 0.0`` — i.e.
         no macro surcharge is claimed — and says so.
      3. ``unavailable_failed_ship_gate`` — a pipeline exists but its recorded
         val_accuracy does not beat its persistence baseline. Same documented
         default. See ``app/ml/regime_model.evaluate_ship_gate``.

    This docstring previously asserted the opposite of (1) — that the artifacts
    were untracked and "on the deployed image they simply do not exist", making
    branch 2 sound like the production case. A code reader was being told the
    reverse of what production does.
    """
    from app.ml.regime_model import (
        REGIME_UNAVAILABLE_STRESS_PROB,
        evaluate_ship_gate,
        get_current_stress_prob,
    )

    gate = evaluate_ship_gate((metrics or {}).get("regime"))
    pipe = model_store.load("regime")
    features = model_store.load("regime_features")

    if not gate["passed"]:
        status = {
            "available": False,
            "source": "unavailable_failed_ship_gate" if pipe is not None else "unavailable_no_artifact",
            "reason": gate["reason"] if pipe is not None else (
                f"{model_store.path('regime')} is absent — no regime model is loadable "
                f"at this path. Ship-gate record: {gate['reason']}"
            ),
            "fallback_stress_prob": REGIME_UNAVAILABLE_STRESS_PROB,
            "ship_gate": gate,
            "metrics": (metrics or {}).get("regime") or {},
        }
        logger.warning("macro regime signal UNAVAILABLE (%s): %s", status["source"], status["reason"])
        return None, None, REGIME_UNAVAILABLE_STRESS_PROB, status

    if pipe is None or features is None:
        status = {
            "available": False,
            "source": "unavailable_no_artifact",
            "reason": (
                f"{model_store.path('regime')} / {model_store.path('regime_features')} are absent "
                "(not git-tracked) — no regime model is deployed on this instance."
            ),
            "fallback_stress_prob": REGIME_UNAVAILABLE_STRESS_PROB,
            "ship_gate": gate,
            "metrics": (metrics or {}).get("regime") or {},
        }
        logger.warning("macro regime signal UNAVAILABLE: %s", status["reason"])
        return None, None, REGIME_UNAVAILABLE_STRESS_PROB, status

    try:
        prob = get_current_stress_prob(pipe, features)
    except Exception as exc:  # noqa: BLE001 — a broken artifact must not fake a signal
        status = {
            "available": False,
            "source": "unavailable_inference_error",
            "reason": f"regime inference failed: {type(exc).__name__}: {exc}",
            "fallback_stress_prob": REGIME_UNAVAILABLE_STRESS_PROB,
            "ship_gate": gate,
            "metrics": (metrics or {}).get("regime") or {},
        }
        logger.warning("macro regime signal UNAVAILABLE: %s", status["reason"])
        return None, None, REGIME_UNAVAILABLE_STRESS_PROB, status

    status = {
        "available": True,
        "source": "model",
        "reason": gate["reason"],
        "computed_at": _now(),
        "ship_gate": gate,
        # Full walk-forward metrics so /ml/stress can publish the scoring-rule
        # evidence next to the probability it is serving.
        "metrics": (metrics or {}).get("regime") or {},
    }
    return pipe, features, float(prob), status


def _check_feature_schema(feature_cols: Any) -> Tuple[bool, Optional[str]]:
    """Is the persisted lead-time feature schema the one this code builds?

    Serving an artifact whose column names this code does not produce is exactly
    how the constant-62.1-day predictor happened: the old aligner zero-filled
    every unrecognised name instead of failing. Now it fails, loudly, at startup.
    """
    from app.ml.lead_time_model import FEATURE_SCHEMA_VERSION, parse_feature_cols

    try:
        parse_feature_cols(feature_cols or [])
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, (
            f"persisted feature_cols are not lead-time feature schema "
            f"v{FEATURE_SCHEMA_VERSION}: {exc}"
        )


def load_ml_state() -> Optional[MLState]:
    """Build the serving :class:`MLState` — champion if resolvable, else disk.

    Returns ``None`` when no models are present at all (fresh checkout that never
    ran training); callers already treat that as "ML disabled".
    """
    if not model_store.models_exist():
        logger.warning("no ML artifacts on disk — ML endpoints will report 503")
        return None

    lt_models = model_store.load("lead_time") or {}
    feature_cols = model_store.load("feature_cols") or []
    metrics = model_store.load("metrics") or {}

    regime_pipe, regime_features, stress, regime_status = resolve_regime_signal(metrics)

    schema_ok, schema_error = _check_feature_schema(feature_cols)
    if not schema_ok:
        logger.error(
            "lead-time artifacts REFUSED: %s. Retrain with `python -m seeds.train_ml_models`; "
            "no prediction will be served until then.", schema_error,
        )

    best = metrics.get("best_lead_time_model")
    if not best and lt_models:
        best = min(
            lt_models,
            key=lambda k: lt_models[k].get("cv_rmse_mean", lt_models[k].get("rmse", float("inf"))),
        )

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
        prov = _artifact_provenance(best, reason, metrics.get("provenance"))
        logger.info(
            "serving lead-time model from on-disk artifact %s (model=%s) — MLflow champion "
            "not used: %s",
            prov["model_uri"], best, reason,
        )

    prov["n_training_samples"] = metrics.get("n_training_samples")
    prov["n_features"] = metrics.get("n_features") or (len(feature_cols) or None)
    prov["feature_schema_version"] = metrics.get("feature_schema_version")
    prov["feature_schema_ok"] = schema_ok
    prov["feature_schema_error"] = schema_error
    # Naive baselines recorded at fit time — /ml/model-comparison publishes them
    # next to the model metrics so the R² is never quoted without its floor.
    prov["lead_time_baselines"] = metrics.get("lead_time_baselines")
    prov["lead_time_beats_baselines"] = metrics.get("lead_time_beats_baselines")
    prov["lead_time_toughest_baseline"] = metrics.get("lead_time_toughest_baseline")
    prov["lead_time_skill_vs_toughest_baseline"] = metrics.get("lead_time_skill_vs_toughest_baseline")
    prov["lead_time_paired_vs_toughest_baseline"] = metrics.get(
        "lead_time_paired_vs_toughest_baseline"
    )
    prov["feature_exclusions"] = metrics.get("feature_exclusions")
    prov["artifact_provenance"] = metrics.get("provenance")
    # WARN, never fail: the weekly collector commits a new panel cross-section
    # every Monday and the models are retrained by hand, so a hash mismatch is
    # expected drift, not a defect. Surfacing it here (and on GET /ml/model-info)
    # is what makes the collector's growth visible instead of silently ignored.
    prov["missing_provenance_fields"] = model_store.missing_provenance_fields(
        metrics.get("provenance")
    )
    staleness = model_store.check_training_data_staleness(metrics.get("provenance"))
    prov["training_data_staleness"] = staleness
    if staleness.get("stale"):
        logger.warning("lead-time artifact staleness — %s", staleness["detail"])
    if prov["missing_provenance_fields"]:
        logger.warning(
            "lead-time artifact is missing provenance field(s) %s — you cannot tell "
            "which data produced this model. Retrain with `python -m seeds.train_ml_models`.",
            prov["missing_provenance_fields"],
        )
    prov["lead_time_leakage_audit"] = metrics.get("lead_time_leakage_audit")
    prov["lead_time_ship_gate"] = metrics.get("lead_time_ship_gate")
    prov["lead_time_n_manufacturers"] = metrics.get("lead_time_n_manufacturers")

    if not schema_ok:
        # Refuse to serve rather than zero-fill an unrecognised schema.
        serving_model = None

    return MLState(
        regime_model=regime_pipe,
        regime_features=regime_features,
        lead_time_models=lt_models,
        best_lead_time_model=best,
        current_stress_prob=stress,
        feature_columns=feature_cols,
        serving_model=serving_model,
        provenance=prov,
        regime_status=regime_status,
    )


def get_serving_model(state: Optional[MLState]) -> Optional[Any]:
    """The single estimator that actually answers predictions for ``state``.

    Returns ``None`` when the persisted feature schema is not the one this code
    builds — serving through a mismatched schema is the defect this module now
    fails closed on.
    """
    if state is None:
        return None
    prov = getattr(state, "provenance", None) or {}
    if prov.get("feature_schema_ok") is False:
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
