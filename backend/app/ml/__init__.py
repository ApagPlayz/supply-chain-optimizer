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


def set_ml_state(state: MLState) -> None:
    global _ml_state
    _ml_state = state


def get_ml_state() -> Optional[MLState]:
    return _ml_state
