"""
Multi-model lead time predictor.

Trains four scikit-learn regressors on a feature matrix derived from:
  - Sourceability category baselines (base lead days by component type)
  - Per-offer features from the existing DB (distance, tier, domestic, risk)
  - Current macro stress probability from the regime model (Task 3)

Target variable construction:
  target_days = base_days × stress_multiplier × distance_modifier
  where:
    stress_multiplier = 1.0 + 1.5 × macro_stress_prob   (up to 2.5× at full crisis)
    distance_modifier = 1.0 + (dist_km / 20_000)        (small penalty for distant intl)

The four models compete on a held-out 20% test split. The best model
(lowest RMSE) is used in costs.py for live lead time inference.

Model comparison metrics are exposed via GET /api/v1/ml/model-comparison.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.lead_time_labels import get_base_days

# Four competing models
MODELS: Dict = {
    "ridge": Pipeline([
        ("scaler", StandardScaler()),
        ("model", Ridge(alpha=1.0)),
    ]),
    "random_forest": RandomForestRegressor(
        n_estimators=100, min_samples_leaf=3, random_state=42
    ),
    "gradient_boosting": GradientBoostingRegressor(
        n_estimators=100, learning_rate=0.1, max_depth=4, random_state=42
    ),
    "mlp": Pipeline([
        ("scaler", StandardScaler()),
        ("model", MLPRegressor(
            hidden_layer_sizes=(64, 32),
            activation="relu",
            max_iter=500,
            random_state=42,
        )),
    ]),
}

_TIER_MAP = {"major": 0, "mid": 1, "broker": 2}


def build_feature_row(
    category: str,
    is_domestic: bool,
    dist_km: float,
    tier: str,
    macro_stress: float,
    risk_score: float,
    stock_coverage: float,
    is_chinese_origin: bool,
) -> Dict:
    """
    Build a single feature dict for one (offer, distributor) pair.
    Category is left as a string here; build_training_matrix one-hot encodes it.
    """
    return {
        "category": category,
        "is_domestic": int(is_domestic),
        "dist_km": float(dist_km),
        "tier": _TIER_MAP.get(tier, 1),
        "macro_stress": float(macro_stress),
        "risk_score": float(risk_score),
        "stock_coverage": min(float(stock_coverage), 50.0),
        "is_chinese_origin": int(is_chinese_origin),
    }


def build_training_matrix(
    rows: List[Dict],
    targets: List[float],
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    One-hot encode the category column and return (X, y, feature_column_names).
    feature_column_names is needed at inference time to align new rows.
    """
    df = pd.DataFrame(rows)
    df = pd.get_dummies(df, columns=["category"], drop_first=False)
    y = np.array(targets, dtype=float)
    cols = list(df.columns)
    return df.values.astype(float), y, cols


def _align_row(row: Dict, feature_cols: List[str]) -> np.ndarray:
    """Convert a single feature dict to a 1×N array using the training column order."""
    df = pd.DataFrame([row])
    df = pd.get_dummies(df, columns=["category"], drop_first=False)
    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0
    df = df[feature_cols]
    return df.values.astype(float)


def train_all_models(
    X: np.ndarray,
    y: np.ndarray,
) -> Dict[str, Dict]:
    """
    Train all four models on 80% of data, evaluate on 20% holdout.
    Returns dict: {model_name: {"model": fitted, "rmse": float, "mae": float, "r2": float}}
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    results: Dict[str, Dict] = {}
    for name, blueprint in MODELS.items():
        m = copy.deepcopy(blueprint)
        m.fit(X_train, y_train)
        y_pred = m.predict(X_test)
        rmse = float(np.sqrt(np.mean((y_pred - y_test) ** 2)))
        mae = float(mean_absolute_error(y_test, y_pred))
        r2 = float(r2_score(y_test, y_pred))
        results[name] = {
            "model": m,
            "rmse": round(rmse, 2),
            "mae": round(mae, 2),
            "r2": round(r2, 4),
        }
    return results


def predict_lead_time(
    model,
    feature_row: Dict,
    feature_cols: List[str],
) -> float:
    """Predict lead time in days for a single offer."""
    X = _align_row(feature_row, feature_cols)
    return max(float(model.predict(X)[0]), 1.0)


def compute_target(
    category: str,
    dist_km: float,
    macro_stress: float,
) -> float:
    """
    Construct the training target for one offer.
    target = Sourceability_base × stress_multiplier × distance_modifier
    """
    base = get_base_days(category)
    stress_mult = 1.0 + 1.5 * macro_stress
    dist_mod = 1.0 + (dist_km / 20_000.0)
    return base * stress_mult * dist_mod
