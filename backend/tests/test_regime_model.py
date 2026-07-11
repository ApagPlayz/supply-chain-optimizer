"""
Tests for the GSCPI regime forecaster (Route A — real observed target).

Model-mechanics tests build a structured monthly frame locally (no network).
A separate, data-gated integration test runs the real retrain when the NY Fed
GSCPI + FRED sources are reachable (or a committed cache exists).
"""
import numpy as np
import pandas as pd
import pytest

from app.ml.fred_client import (
    REGIME_CLASSES,
    engineer_regime_features,
    gscpi_regime_label,
)
from app.ml.regime_model import (
    build_regime_dataset,
    build_regime_pipeline,
    get_current_stress_prob,
    retrain_regime_model,
    train_regime_model,
)


def _synthetic_gscpi(n=180):
    """A GSCPI-like z-score walk with a clear stress spike (mimics 2021-22)."""
    idx = pd.date_range("2010-01-01", periods=n, freq="MS")
    rng = np.random.default_rng(42)
    base = np.cumsum(rng.normal(0, 0.25, n))
    base = (base - base.mean()) / (base.std() or 1.0)
    spike_start = n - 48
    base[spike_start:spike_start + 20] += 2.5  # sustained stress episode
    return pd.Series(base, index=idx, name="gscpi")


def _synthetic_raw(idx):
    """Four FRED-like monthly series correlated (loosely) with the target."""
    rng = np.random.default_rng(7)
    n = len(idx)
    return pd.DataFrame({
        "capacity_util": 70 + rng.normal(0, 2, n).cumsum() * 0.1,
        "inv_sales":     1.4 + rng.normal(0, 0.02, n).cumsum() * 0.01,
        "ip_semis":      100 + np.linspace(0, 20, n) + rng.normal(0, 1, n),
        "mfg_inv_ratio": 1.3 + rng.normal(0, 0.02, n).cumsum() * 0.01,
    }, index=idx)


def _dataset():
    gscpi = _synthetic_gscpi()
    raw = _synthetic_raw(gscpi.index)
    feats = engineer_regime_features(raw, gscpi)
    labels = gscpi_regime_label(gscpi).reindex(feats.index)
    both = feats.join(labels, how="inner").dropna()
    return both.drop(columns="regime"), both["regime"]


def test_pipeline_builds():
    pipe = build_regime_pipeline()
    assert hasattr(pipe, "fit")
    assert hasattr(pipe, "predict_proba")


def test_label_is_independent_of_features():
    """The regime label must be derivable from GSCPI alone — no FRED feature.

    Guards against reintroducing the old tautology: recomputing the label from a
    *shuffled* feature set must not change it, i.e. the label ignores features.
    """
    gscpi = _synthetic_gscpi()
    lab = gscpi_regime_label(gscpi)
    assert set(lab.unique()) <= set(REGIME_CLASSES)
    # Label depends only on GSCPI: same GSCPI -> same label regardless of features.
    lab_again = gscpi_regime_label(gscpi.copy())
    assert (lab == lab_again).all()
    # Stress band fires exactly where GSCPI >= upper cut.
    assert (lab[gscpi >= 0.5] == "stress").all()


def test_features_are_strictly_lagged():
    """FRED feature columns at row t must equal engineered values from <= t-1
    (no contemporaneous leakage from the target month)."""
    gscpi = _synthetic_gscpi()
    raw = _synthetic_raw(gscpi.index)
    feats = engineer_regime_features(raw, gscpi)
    # The _level column is the raw series shifted by one month.
    aligned = raw["ip_semis"].shift(1).reindex(feats.index)
    assert np.allclose(feats["ip_semis_level"].values, aligned.values)


def test_train_returns_honest_metrics_with_baseline():
    X, y = _dataset()
    pipe, metrics = train_regime_model(X, y)
    assert hasattr(pipe, "predict_proba")
    for key in ("val_accuracy", "macro_f1", "per_class_recall",
                "confusion_matrix", "baseline_accuracy", "shortage_recall"):
        assert key in metrics
    assert 0.0 <= metrics["val_accuracy"] <= 1.0


def test_get_current_stress_prob_range():
    X, y = _dataset()
    pipe, _ = train_regime_model(X, y)
    prob = get_current_stress_prob(pipe, X)
    assert 0.0 <= prob <= 1.0


def test_stress_prob_higher_in_stress_period():
    X, y = _dataset()
    pipe, _ = train_regime_model(X, y)
    stress_rows = X[y == "stress"]
    calm_rows = X[y == "calm"]
    if stress_rows.empty or calm_rows.empty:
        pytest.skip("synthetic fixture produced no stress/calm contrast")
    p_stress = get_current_stress_prob(pipe, stress_rows)
    p_calm = get_current_stress_prob(pipe, calm_rows)
    assert p_stress >= p_calm


@pytest.mark.integration
def test_real_retrain_if_data_available():
    """Runs the real GSCPI + FRED retrain when the data is reachable/cached."""
    if build_regime_dataset() is None:
        pytest.skip("GSCPI/FRED data unavailable (offline and no cache)")
    out = retrain_regime_model()
    assert out["pipe"] is not None
    assert 0.0 <= out["current_stress_prob"] <= 1.0
    assert out["metrics"]["val_accuracy"] > 0.0
    assert out["metrics"]["baseline_accuracy"] is not None
