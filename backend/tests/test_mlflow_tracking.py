"""
Tests for MLflow experiment tracking + registry (P5).

These use tiny synthetic DummyRegressor models ONLY to exercise the logging and
champion-selection logic in isolation (clearly a test fixture, not production
data). Each test points MLflow at a per-test temporary SQLite store via the
MLFLOW_TRACKING_URI env var so nothing touches the real backend/mlruns store.
"""
import numpy as np
import pytest
from sklearn.dummy import DummyRegressor

import app.ml.mlflow_tracking as mt


def _fitted_dummy():
    X = np.array([[0.0], [1.0], [2.0]])
    y = np.array([1.0, 2.0, 3.0])
    return DummyRegressor(strategy="mean").fit(X, y)


def _fake_results():
    """4 fake models with KNOWN rmse — random_forest is the clear winner."""
    return {
        "ridge": {"model": _fitted_dummy(), "rmse": 5.0, "mae": 4.0, "r2": 0.50},
        "random_forest": {"model": _fitted_dummy(), "rmse": 2.0, "mae": 1.5, "r2": 0.90},
        "gradient_boosting": {"model": _fitted_dummy(), "rmse": 8.0, "mae": 6.0, "r2": 0.20},
        "mlp": {"model": _fitted_dummy(), "rmse": 3.0, "mae": 2.5, "r2": 0.70},
    }


@pytest.fixture
def tmp_tracking(tmp_path, monkeypatch):
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    return uri


def test_log_lead_time_models_runs_without_error(tmp_tracking):
    out = mt.log_lead_time_models(_fake_results(), n_samples=3, n_features=1)
    assert set(out["run_ids"]) == {"ridge", "random_forest", "gradient_boosting", "mlp"}
    # Every model produced a real run id.
    assert all(isinstance(rid, str) and rid for rid in out["run_ids"].values())


def test_champion_is_lowest_rmse_run(tmp_tracking):
    out = mt.log_lead_time_models(_fake_results(), n_samples=3, n_features=1)
    champ = out["champion"]
    assert champ is not None
    assert champ["model_name"] == "random_forest"  # rmse 2.0 is the minimum
    assert champ["value"] == pytest.approx(2.0)
    assert champ["metric"] == "rmse"


def test_champion_alias_resolves_in_registry(tmp_tracking):
    from mlflow.tracking import MlflowClient

    out = mt.log_lead_time_models(_fake_results(), n_samples=3, n_features=1)
    champ = out["champion"]

    client = MlflowClient()
    mv = client.get_model_version_by_alias(mt.LEAD_TIME_MODEL, mt.CHAMPION_ALIAS)
    assert mv.version == champ["version"]
    assert mv.tags.get("selection_metric") == "rmse"


def test_select_champion_separately(tmp_tracking):
    # Log without registering, then select explicitly — same result.
    mt.log_lead_time_models(_fake_results(), n_samples=3, n_features=1, register_champion=False)
    champ = mt.select_champion(mt.LEAD_TIME_EXPERIMENT, mt.LEAD_TIME_MODEL, metric="rmse")
    assert champ["model_name"] == "random_forest"
    assert champ["value"] == pytest.approx(2.0)


def test_select_champion_raises_for_empty_experiment(tmp_tracking):
    mt.configure_mlflow("an_empty_experiment")
    with pytest.raises(ValueError):
        mt.select_champion("an_empty_experiment", "nothing_here", metric="rmse")
