"""
Macro supply-chain regime forecasting — multinomial logistic regression.

Route A overhaul (2026-07-01): the previous classifier was a TAUTOLOGY — its
label was a threshold on its own input features (capacity_util >= 75 AND
inventory_ratio <= 1.35), so recall was ~1.0 by construction. It is replaced
here with a genuine one-month-ahead forecasting task against an INDEPENDENT,
externally-published target.

Target (independent of the features):
    NY Fed Global Supply Chain Pressure Index (GSCPI) z-score, banded into
    calm / elevated / stress at (-0.5, 0.5). GSCPI is constructed from global
    transportation costs + PMI supplier-delivery data — a different data domain
    from the US-semiconductor FRED features — so no feature is a function of the
    label. See fred_client.gscpi_regime_label / engineer_regime_features.

Features (strictly lagged, no contemporaneous target leakage):
    Lagged CAPUTLG3344S / U34SIS / IPG3344S / MNFCTRIRSA (level, 3m momentum,
    12m z-score), plus an autoregressive GSCPI block (lag 1/2/3 + 3m change).

Evaluation is HONEST and always benchmarked against a persistence baseline
(regime_t = regime_{t-1}). See train_regime_model for the reported metrics.

Serving contract (unchanged for costs.py / sourcing.py / api/ml.py):
    get_current_stress_prob(pipe, features_df) -> P(regime == "stress") in [0,1].

Citations:
    Benigno et al. (2022), NY Fed — GSCPI construction.
    Marler & Arora (2004) — weighted scalarization (downstream optimizer use).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.fred_client import (
    REGIME_CLASSES,
    engineer_regime_features,
    fetch_gscpi,
    fetch_regime_feature_frame,
    gscpi_regime_label,
)

STRESS_CLASS = "stress"

# Time-ordered split (covers COVID + the 2021-22 shortage + 2022-23 normalisation).
DEFAULT_TRAIN_END = "2019-01-01"
DEFAULT_VAL_START = "2019-01-01"
DEFAULT_VAL_END = "2023-12-31"

# L2 strength chosen by expanding-window (TimeSeriesSplit) CV on the training
# window only — never tuned on the validation holdout.
DEFAULT_C = 0.2


def build_regime_pipeline(C: float = DEFAULT_C) -> Pipeline:
    """StandardScaler + L2 multinomial logistic regression.

    class_weight='balanced' compensates for regime imbalance (calm/elevated
    dominate history; the stress regime is rarer).
    """
    return Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(
            C=C,
            class_weight="balanced",
            solver="lbfgs",
            max_iter=5000,
            random_state=42,
        )),
    ])


def _persistence_accuracy(labels: pd.Series, mask) -> Optional[float]:
    """Accuracy of the naive baseline regime_t = regime_{t-1} on ``mask`` rows."""
    mask = np.asarray(getattr(mask, "values", mask))
    prev = labels.shift(1)
    idx = labels.index[mask]
    prev_vals = prev.reindex(idx)
    true_vals = labels.reindex(idx)
    ok = prev_vals.notna()
    if not ok.any():
        return None
    return round(float((prev_vals[ok].values == true_vals[ok].values).mean()), 4)


def train_regime_model(
    features_df: pd.DataFrame,
    labels: pd.Series,
    C: float = DEFAULT_C,
    train_end: str = DEFAULT_TRAIN_END,
    val_start: str = DEFAULT_VAL_START,
    val_end: str = DEFAULT_VAL_END,
) -> Tuple[Pipeline, Dict]:
    """Fit on the pre-``train_end`` window; report HONEST metrics on the holdout.

    Returns:
        pipe    : fitted sklearn Pipeline
        metrics : dict with (all rounded)
                  val_accuracy, macro_f1, baseline_accuracy (persistence),
                  per_class_recall {class: recall}, confusion_matrix (list of
                  lists, row/col order == classes), classes, val_size, and
                  shortage_recall == recall of the "stress" class (back-compat
                  key consumed by the training log).
    """
    labels = labels.reindex(features_df.index)
    train_mask = features_df.index < train_end
    val_mask = (features_df.index >= val_start) & (features_df.index <= val_end)

    X_train = features_df[train_mask].values
    y_train = labels[train_mask].values

    pipe = build_regime_pipeline(C=C)
    pipe.fit(X_train, y_train)
    classes = list(pipe.classes_)

    if val_mask.sum() > 0:
        X_val = features_df[val_mask].values
        y_val = labels[val_mask].values
    else:
        # Too little data for the calendar holdout (e.g. tiny test fixtures):
        # fall back to scoring the full set so the interface still returns.
        X_val, y_val = features_df.values, labels.values
        val_mask = pd.Series(True, index=features_df.index)

    y_pred = pipe.predict(X_val)
    per_class = recall_score(y_val, y_pred, labels=classes, average=None, zero_division=0)
    stress_recall = per_class[classes.index(STRESS_CLASS)] if STRESS_CLASS in classes else 0.0

    metrics: Dict = {
        "target": "NY Fed GSCPI regime (calm/elevated/stress) — one-month-ahead",
        "classes": classes,
        "val_accuracy": round(float((y_pred == y_val).mean()), 4),
        "macro_f1": round(float(f1_score(y_val, y_pred, labels=classes,
                                         average="macro", zero_division=0)), 4),
        "per_class_recall": {c: round(float(r), 4) for c, r in zip(classes, per_class)},
        "confusion_matrix": confusion_matrix(y_val, y_pred, labels=classes).tolist(),
        "baseline_accuracy": _persistence_accuracy(labels, val_mask),
        "val_size": int(val_mask.sum()),
        # Back-compat: the orchestrator logs "shortage_recall"; it now means the
        # recall of the stress regime (still an honest, learned quantity).
        "shortage_recall": round(float(stress_recall), 4),
    }
    return pipe, metrics


def get_current_stress_prob(pipe: Pipeline, features_df: pd.DataFrame) -> float:
    """P(regime == "stress") for the most recent feature row. 0.0 if empty.

    Interface unchanged from the legacy binary model: costs.py / sourcing.py /
    api/ml.py consume this single stress probability in [0, 1].
    """
    if features_df is None or len(features_df) == 0:
        return 0.0
    classes = list(pipe.classes_)
    if STRESS_CLASS not in classes:
        return 0.0
    X = features_df.tail(1).values
    proba = pipe.predict_proba(X)[0]
    return float(proba[classes.index(STRESS_CLASS)])


def build_regime_dataset() -> Optional[Tuple[pd.DataFrame, pd.Series]]:
    """Fetch GSCPI + FRED features and assemble (features_df, labels).

    Returns None if the real data cannot be obtained from network or cache.
    """
    gscpi = fetch_gscpi()
    raw = fetch_regime_feature_frame()
    if gscpi is None or raw is None:
        return None
    features_df = engineer_regime_features(raw, gscpi)
    labels = gscpi_regime_label(gscpi).reindex(features_df.index)
    both = features_df.join(labels, how="inner").dropna()
    if both.empty:
        return None
    labels = both["regime"]
    features_df = both.drop(columns="regime")
    return features_df, labels


def retrain_regime_model(C: float = DEFAULT_C) -> Dict:
    """End-to-end retrain the orchestrator (train_ml_models.py) calls.

    Fetches the real GSCPI target + lagged FRED features, trains the model with
    a time-ordered split, and returns everything needed for persistence and
    serving. Degrades gracefully (pipe=None, stress=0.0) if the real data is
    unavailable, so a training run never hard-fails on a transient outage.

    Returns dict:
        pipe                : fitted Pipeline or None
        features            : feature matrix (persist as "regime_features")
        labels              : regime label Series (or None)
        metrics             : honest metrics dict (see train_regime_model)
        current_stress_prob : P(stress) on the latest row (0.0 if no model)
    """
    dataset = build_regime_dataset()
    if dataset is None:
        return {
            "pipe": None,
            "features": None,
            "labels": None,
            "metrics": {"val_accuracy": 0.0, "shortage_recall": 0.0, "baseline_accuracy": None},
            "current_stress_prob": 0.0,
        }
    features_df, labels = dataset
    pipe, metrics = train_regime_model(features_df, labels, C=C)
    current = get_current_stress_prob(pipe, features_df)
    return {
        "pipe": pipe,
        "features": features_df,
        "labels": labels,
        "metrics": metrics,
        "current_stress_prob": current,
    }
