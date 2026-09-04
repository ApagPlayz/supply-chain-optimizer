"""
ML Supply Chain Intelligence.

Two models:
  1. MacroStressModel  — logistic regression on 6 FRED time series predicting
                          semiconductor shortage stress regime.
  2. LeadTimeModel     — 4 regressors (Ridge, RF, GBM, MLP) predicting component
                          delivery lead time per (offer, distributor, macro_stress).

Call get_ml_state() to get the currently loaded model objects, or None if models
have not been trained yet (run seeds/train_ml_models.py first).
"""
from __future__ import annotations
import threading
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class MLState:
    regime_model: object          # fitted sklearn Pipeline (LogisticRegression)
    regime_features: object       # pd.DataFrame — latest FRED features for inference
    lead_time_models: dict        # {name: {"model": ..., "rmse": ..., "mae": ..., "r2": ...}}
    best_lead_time_model: str     # name of model with lowest RMSE
    current_stress_prob: float    # 0-1, most recent macro stress probability
    feature_columns: list         # column order for lead time inference

    # ── serve-time provenance (app/ml/serving.py) ────────────────────────────
    # serving_model is THE estimator that answers predictions. It is the MLflow
    # `champion`-aliased model version when a registry is reachable, otherwise the
    # best model from the committed lead_time.joblib. `provenance` records which,
    # and is surfaced verbatim by GET /api/v1/ml/model-info.
    serving_model: Optional[Any] = None
    provenance: Optional[dict] = field(default=None)

    # ── regime-signal availability (app/ml/serving.py) ────────────────────────
    # `current_stress_prob` above is ONLY meaningful when regime_status says the
    # signal is live. `regime.joblib` is not git-tracked, so on the deployed
    # image there is no regime model and the honest value is 0.0 (= "no macro
    # surcharge claimed"), not the 0.9967 scalar that used to be replayed out of
    # metrics.joblib months after it was computed. regime_status carries
    # {"available": bool, "reason": str, "source": str, "ship_gate": {...}}.
    regime_status: Optional[dict] = field(default=None)


_ml_state: Optional[MLState] = None

# Bumped by EVERY set_ml_state. The startup warm-up (app/startup.py) records it when
# it STARTS and publishes only if it has not moved, so a slow background load can
# never overwrite a state that somebody installed deliberately while it ran.
#
# This is not hypothetical. The artifact load used to finish inside the ASGI lifespan,
# i.e. before `with TestClient(app)` returned, so a test could set its own MLState
# straight afterwards and be sure of it. Once the load moved onto a background thread,
# `tests/test_stress_vintage.py` and `tests/test_model_serving.py` started failing:
# they installed a stub state, the real load landed a beat later on top of it, and
# `/ml/stress` answered `available: true` for a stub that said false.
_ml_state_epoch: int = 0
_ml_state_lock = threading.Lock()


def set_ml_state(state: MLState) -> None:
    global _ml_state, _ml_state_epoch
    with _ml_state_lock:
        _ml_state = state
        _ml_state_epoch += 1


def get_ml_state() -> Optional[MLState]:
    return _ml_state


def ml_state_epoch() -> int:
    """How many times the process MLState has been assigned. Diagnostics/warm-up."""
    return _ml_state_epoch


def install_ml_state_if_unchanged(state: MLState, epoch: int) -> bool:
    """
    Publish ``state`` only if the MLState has not been assigned since ``epoch``.

    Used by the background warm-up so that a load which started before someone else
    installed a state loses the race instead of silently winning it. Returns True if
    the state was installed.
    """
    global _ml_state, _ml_state_epoch
    with _ml_state_lock:
        if _ml_state_epoch != epoch:
            return False
        _ml_state = state
        _ml_state_epoch += 1
        return True
