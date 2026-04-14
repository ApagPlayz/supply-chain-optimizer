"""
Tests for the macro stress logistic regression.
Uses synthetic data that mirrors real FRED patterns.
"""
import pandas as pd
import pytest
from app.ml.fred_client import engineer_features, compute_stress_label
from app.ml.regime_model import build_regime_pipeline, train_regime_model, get_current_stress_prob


def _build_training_df():
    """
    60 months: first 36 normal (stress=0), last 24 stress (stress=1).
    Mirrors pre-2021 normal + 2021-2022 shortage.
    """
    idx = pd.date_range("2015-01-01", periods=60, freq="MS")
    data = {
        "ppi_semis":       [100.0 + i * 0.3 for i in range(60)],
        "capacity_util":   [68.0 if i < 36 else 76.5 for i in range(60)],
        "inventory_ratio": [1.42 if i < 36 else 1.28 for i in range(60)],
        "industrial_prod": [155.0 + i * 0.2 for i in range(60)],
        "import_price":    [80.0 + i * 0.1 for i in range(60)],
        "freight_tsi":     [118.0 + i * 0.05 for i in range(60)],
    }
    return pd.DataFrame(data, index=idx)


def test_pipeline_builds():
    pipe = build_regime_pipeline()
    assert hasattr(pipe, "fit")
    assert hasattr(pipe, "predict_proba")


def test_train_regime_model_returns_fitted_pipeline():
    df = _build_training_df()
    features = engineer_features(df)
    labels = compute_stress_label(df).reindex(features.index).fillna(0).astype(int)
    pipe, metrics = train_regime_model(features, labels)
    assert hasattr(pipe, "predict_proba")
    assert "val_accuracy" in metrics
    assert "shortage_recall" in metrics


def test_regime_model_flags_stress_period():
    """Model trained on normal data must fire on the stress period."""
    df = _build_training_df()
    features = engineer_features(df)
    labels = compute_stress_label(df).reindex(features.index).fillna(0).astype(int)
    pipe, metrics = train_regime_model(features, labels)
    # shortage recall: what fraction of actual stress months were caught?
    assert metrics["shortage_recall"] >= 0.70


def test_get_current_stress_prob_range():
    df = _build_training_df()
    features = engineer_features(df)
    labels = compute_stress_label(df).reindex(features.index).fillna(0).astype(int)
    pipe, _ = train_regime_model(features, labels)
    prob = get_current_stress_prob(pipe, features)
    assert 0.0 <= prob <= 1.0


def test_stress_prob_higher_in_stress_period():
    df = _build_training_df()
    features = engineer_features(df)
    labels = compute_stress_label(df).reindex(features.index).fillna(0).astype(int)
    pipe, _ = train_regime_model(features, labels)
    # Stress prob from the last row (stress period) should exceed first row (normal)
    prob_normal = float(pipe.predict_proba(features.iloc[[0]])[0][1])
    prob_stress = float(pipe.predict_proba(features.iloc[[-1]])[0][1])
    assert prob_stress > prob_normal
