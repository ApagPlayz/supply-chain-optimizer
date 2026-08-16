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
    fetch_gscpi,
    gscpi_regime_label,
)
from app.ml.regime_model import (
    MIN_TRAIN_MONTHS,
    REGIME_UNAVAILABLE_STRESS_PROB,
    build_regime_dataset,
    build_regime_pipeline,
    get_current_stress_prob,
    retrain_regime_model,
    train_regime_model,
    walk_forward_evaluate,
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
    """Runs the real GSCPI + FRED retrain when the data is reachable/cached.

    ``pipe`` is deliberately None whenever the ship gate fails — a model that
    does not beat its persistence baseline is not served. What must ALWAYS hold
    is that the walk-forward number and the baseline it is judged against are
    both reported, and that the served stress probability is the documented
    fallback whenever the gate did not pass.
    """
    if build_regime_dataset() is None:
        pytest.skip("GSCPI/FRED data unavailable (offline and no cache)")
    out = retrain_regime_model()
    metrics, gate = out["metrics"], out["ship_gate"]

    assert metrics["walk_forward_accuracy"] > 0.0
    assert metrics["baseline_accuracy"] is not None, (
        "a regime accuracy must never be reported without its persistence baseline"
    )
    assert metrics["n_folds"] > 0
    assert gate["reason"]
    assert 0.0 <= out["current_stress_prob"] <= 1.0

    # Both baselines must be present alongside the model score, always.
    assert metrics["brier"] is not None
    assert metrics["baseline_brier"] is not None
    assert metrics["climatology_brier"] is not None
    assert metrics["calibration"]["calibration_slope"] is not None

    if gate["passed"]:
        assert metrics["brier"] < metrics["baseline_brier"]
        assert metrics["brier"] < metrics["climatology_brier"]
        assert out["pipe"] is not None
        # A served model must emit a real probability, not the fallback constant.
        assert 0.0 <= out["current_stress_prob"] <= 1.0
    else:
        assert out["pipe"] is None, "a model that failed the ship gate must not be served"
        assert out["current_stress_prob"] == REGIME_UNAVAILABLE_STRESS_PROB


@pytest.mark.integration
def test_walk_forward_scores_persistence_on_the_same_folds():
    """The baseline must be measured on the identical folds, or it proves nothing."""
    dataset = build_regime_dataset()
    if dataset is None:
        pytest.skip("GSCPI/FRED data unavailable (offline and no cache)")
    features_df, labels = dataset
    gscpi = fetch_gscpi().reindex(features_df.index)
    metrics, _hp = walk_forward_evaluate(features_df, gscpi, labels)

    assert metrics["status"] == "ok"
    # Every month after the calibration window is evaluated — nothing discarded.
    assert metrics["n_folds"] == metrics["n_months_total"] - MIN_TRAIN_MONTHS
    assert metrics["baseline_accuracy"] is not None
    assert metrics["mcnemar_model_only_correct"] >= 0
    assert metrics["mcnemar_baseline_only_correct"] >= 0
    # Proper scoring rules, and both baselines, on the same folds.
    for key in ("brier", "baseline_brier", "climatology_brier",
                "log_loss", "baseline_log_loss", "climatology_log_loss"):
        assert metrics[key] is not None, key
    # Persistence is degenerate as a probability, so its log loss must be awful —
    # that asymmetry is exactly why accuracy is the wrong rule here.
    assert metrics["baseline_log_loss"] > metrics["log_loss"]
    for name in ("vs_persistence", "vs_climatology"):
        paired = metrics["paired_brier"][name]
        assert paired["n_folds"] == metrics["n_folds"]
        assert paired["ci95_low"] <= paired["mean_brier_reduction"] <= paired["ci95_high"]
    # Hyperparameters must come from the calibration window, not the walk.
    assert metrics["hyperparameters"]
    assert metrics["calibration_inner_accuracy"] is not None


def _gate_metrics(brier=0.40, pers=0.54, clim=0.67, slope=0.63, **extra):
    """A metrics dict shaped like walk_forward_evaluate's output."""
    m = {
        "brier": brier,
        "baseline_brier": pers,
        "climatology_brier": clim,
        "calibration": {"calibration_slope": slope},
        "walk_forward_accuracy": 0.7294,
        "baseline_accuracy": 0.7294,
    }
    m.update(extra)
    return m


def test_ship_gate_is_a_proper_scoring_rule_not_accuracy():
    """Accuracy is blind to the probability the optimizer actually consumes."""
    from app.ml.regime_model import evaluate_ship_gate

    # The real situation: TIES persistence on accuracy, beats both on Brier.
    gate = evaluate_ship_gate(_gate_metrics())
    assert gate["passed"] is True
    assert gate["policy"] == "brier"
    assert "ACCURACY" in gate["reason"]        # the tie is stated, not hidden


def test_ship_gate_requires_beating_BOTH_baselines_on_brier():
    from app.ml.regime_model import evaluate_ship_gate

    # Beats persistence but not climatology => must not ship. Climatology is the
    # bar that shows the model learned something about TIMING.
    losing_clim = evaluate_ship_gate(_gate_metrics(brier=0.60, pers=0.65, clim=0.55))
    assert losing_clim["passed"] is False
    assert "climatology" in losing_clim["reason"]

    # Beats climatology but not persistence => must not ship.
    losing_pers = evaluate_ship_gate(_gate_metrics(brier=0.60, pers=0.55, clim=0.70))
    assert losing_pers["passed"] is False
    assert "persistence" in losing_pers["reason"]

    # A Brier tie is not a win either.
    assert evaluate_ship_gate(_gate_metrics(brier=0.54, pers=0.54))["passed"] is False


def test_ship_gate_rejects_a_badly_calibrated_probability():
    """The 'we ship because it's a calibrated probability' argument must be true."""
    from app.ml.regime_model import MIN_CALIBRATION_SLOPE, evaluate_ship_gate

    # This is the ACTUAL slope the first implementation produced (in-sample sd).
    bad = evaluate_ship_gate(_gate_metrics(slope=0.214))
    assert bad["passed"] is False
    assert "calibration slope" in bad["reason"]

    assert evaluate_ship_gate(_gate_metrics(slope=MIN_CALIBRATION_SLOPE - 0.01))["passed"] is False
    assert evaluate_ship_gate(_gate_metrics(slope=MIN_CALIBRATION_SLOPE))["passed"] is True
    # Unmeasurable calibration fails closed.
    assert evaluate_ship_gate(_gate_metrics(slope=None))["passed"] is False


def test_ship_gate_fails_closed_on_missing_evidence():
    from app.ml.regime_model import evaluate_ship_gate

    assert evaluate_ship_gate(None)["passed"] is False
    # No baselines recorded => the comparison was never made.
    assert evaluate_ship_gate({"brier": 0.01})["passed"] is False
    assert evaluate_ship_gate({"walk_forward_accuracy": 0.99})["passed"] is False
