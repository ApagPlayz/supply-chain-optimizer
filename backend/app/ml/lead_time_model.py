"""
Multi-model lead time predictor.

Trains four scikit-learn regressors (Ridge, RandomForest, GBM, MLP) on REAL
observed lead times collected weekly from the DigiKey + Mouser catalogs and
stored in the panel written by ``app.ml.lead_time_collector``.

Target variable (Route A — real, no leakage):
    target_days = observed lead_time_weeks × 7
where ``lead_time_weeks`` is what a distributor actually quoted for the part on
the snapshot date. Features (part attributes known at prediction time —
category, lifecycle status, stock, source, macro stress) do NOT determine the
target, so the model has something genuine to learn.

>>> IMPORTANT: the old synthetic target (base_days × macro × distance) has been
    QUARANTINED. See ``compute_target`` below — it is deprecated and must NOT be
    used to train a model we then call a "prediction". ``retrain_lead_time`` is
    the real entrypoint; if no observations exist yet it SKIPS training rather
    than falling back to the formula.

The four models compete on a held-out 20% test split. The best model
(lowest RMSE) is used in costs.py for live lead time inference.
Model comparison metrics are exposed via GET /api/v1/ml/model-comparison.
"""
from __future__ import annotations

import copy
import logging
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
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
    DEPRECATED / QUARANTINED — DO NOT use to train the lead-time model.

    This is the old *synthetic* target (base_days × stress_multiplier ×
    distance_modifier). Because it is a deterministic function of the model's
    own inputs, a model trained on it merely memorises this equation (R²≈1.0,
    pure leakage) — it learns nothing about real lead times. Route A replaced it
    with real observed lead times; see ``retrain_lead_time``.

    Retained only so the legacy orchestrator import does not hard-crash during
    migration. It emits a DeprecationWarning and is not called by any real
    training path. Remove once ``seeds/train_ml_models.py`` calls
    ``retrain_lead_time`` instead.
    """
    warnings.warn(
        "compute_target is the deprecated synthetic lead-time formula and must "
        "not be used for training — use retrain_lead_time() on the observed "
        "collector panel instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    base = get_base_days(category)
    stress_mult = 1.0 + 1.5 * macro_stress
    dist_mod = 1.0 + (dist_km / 20_000.0)
    return base * stress_mult * dist_mod


# ── REAL observed-panel training path (Route A) ──────────────────────────────


def load_observed_panel(panel_path: Optional[Path] = None) -> Optional[pd.DataFrame]:
    """
    Load the accumulated observed lead-time panel written by the collector.
    Returns the DataFrame, or None if the panel does not exist / is empty.
    """
    if panel_path is None:
        from app.ml.lead_time_collector import PANEL_PATH
        panel_path = PANEL_PATH
    panel_path = Path(panel_path)
    if not panel_path.exists():
        return None
    df = pd.read_csv(panel_path)
    return df if len(df) else None


def build_observed_matrix(
    df: pd.DataFrame,
    macro_stress: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Build (X, y, feature_cols) from the observed panel.

    Target y = observed lead_time_weeks × 7 (calendar days).
    Features are part attributes known at prediction time — one-hot category and
    source, an is-active lifecycle flag, log-scaled stock, and the current macro
    stress probability. None of these determine y, so there is no leakage.
    """
    d = df.copy()
    d["lead_time_weeks"] = pd.to_numeric(d["lead_time_weeks"], errors="coerce")
    d = d[d["lead_time_weeks"].notna() & (d["lead_time_weeks"] > 0)]
    if d.empty:
        return np.empty((0, 0)), np.empty((0,)), []

    y = (d["lead_time_weeks"].to_numpy(float) * 7.0)

    lifecycle = d.get("lifecycle_status", pd.Series([""] * len(d))).fillna("").astype(str)
    stock = pd.to_numeric(d.get("stock", 0), errors="coerce").fillna(0.0).clip(lower=0)

    base = pd.DataFrame({
        "is_active": lifecycle.str.lower().str.contains("active").astype(int).to_numpy(),
        "log_stock": np.log1p(stock.to_numpy(float)),
        "macro_stress": float(macro_stress),
    }, index=d.index)

    cat = pd.get_dummies(d["category"].fillna("Unknown"), prefix="cat")
    src = pd.get_dummies(d["source"].fillna("unknown"), prefix="src")
    feat = pd.concat([base, cat, src], axis=1)
    return feat.to_numpy(float), y, list(feat.columns)


def retrain_lead_time(
    panel_path: Optional[Path] = None,
    macro_stress: float = 0.0,
    min_samples: int = 30,
) -> Dict:
    """
    REAL entrypoint: train the lead-time regressors on observed data only.

    Reads the collector panel. If it is missing / empty / too small, SKIPS
    training with an honest status (never falls back to the synthetic formula).
    Otherwise trains all four models and returns metrics + fitted models.

    Returns:
        {"status": "skipped", "reason": ..., "n_samples": int}
      or
        {"status": "trained", "n_samples": int, "n_features": int,
         "models": {...}, "feature_cols": [...], "best": name}
    """
    df = load_observed_panel(panel_path)
    if df is None:
        logger.warning(
            "no observed lead times yet — collector must run first; "
            "SKIPPING lead-time training (no synthetic fallback)."
        )
        return {"status": "skipped", "reason": "no_observed_panel", "n_samples": 0}

    X, y, feature_cols = build_observed_matrix(df, macro_stress=macro_stress)
    if len(y) < min_samples:
        logger.warning(
            "only %d observed lead-time rows (< %d needed) — SKIPPING training. "
            "Let the collector accumulate more weekly snapshots first.",
            len(y), min_samples,
        )
        return {"status": "skipped", "reason": "insufficient_observations", "n_samples": int(len(y))}

    results = train_all_models(X, y)
    best = min(results, key=lambda k: results[k]["rmse"])
    logger.info("lead-time retrain on %d REAL observations — best=%s (RMSE=%.1f)",
                len(y), best, results[best]["rmse"])
    return {
        "status": "trained",
        "n_samples": int(len(y)),
        "n_features": int(X.shape[1]),
        "models": results,
        "feature_cols": feature_cols,
        "best": best,
    }
