"""
Serve-time model resolution (app/ml/serving.py).

The gap this closes: training registered models in MLflow and set a `champion`
alias, but the API loaded a joblib off disk and never resolved the alias — the
registry was decorative. These tests pin BOTH real paths:

  * registry reachable -> the model version carrying `champion` is what serves;
  * no registry (the Render free tier) -> the committed joblib serves, and the
    response says so, with the reason.

MLflow always points at a per-test tmp SQLite store (never backend/mlruns).
"""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.dummy import DummyRegressor

import app.ml.mlflow_tracking as mt
import app.ml.serving as serving
from app.ml import MLState


def _fitted_dummy(constant: float) -> DummyRegressor:
    X = np.array([[0.0], [1.0], [2.0]])
    y = np.array([constant, constant, constant])
    return DummyRegressor(strategy="mean").fit(X, y)


def _results():
    """4 models with known RMSE — random_forest wins (lowest RMSE)."""
    return {
        "ridge": {"model": _fitted_dummy(1.0), "rmse": 5.0, "mae": 4.0, "r2": 0.50},
        "random_forest": {"model": _fitted_dummy(2.0), "rmse": 2.0, "mae": 1.5, "r2": 0.90},
        "gradient_boosting": {"model": _fitted_dummy(3.0), "rmse": 8.0, "mae": 6.0, "r2": 0.20},
        "mlp": {"model": _fitted_dummy(4.0), "rmse": 3.0, "mae": 2.5, "r2": 0.70},
    }


@pytest.fixture(autouse=True)
def restore_global_ml_state():
    """MLState is a process-global. Never leak a test dummy into other tests."""
    import app.ml as ml

    previous = ml.get_ml_state()
    yield
    ml.set_ml_state(previous)


@pytest.fixture
def no_registry(tmp_path, monkeypatch):
    """No MLFLOW_TRACKING_URI and no local mlflow.db => registry unreachable."""
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.setattr(mt, "DEFAULT_DB", tmp_path / "does-not-exist.db")
    monkeypatch.setattr(serving, "DEFAULT_DB", tmp_path / "does-not-exist.db")


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    return uri


# ── registry availability ────────────────────────────────────────────────────

def test_registry_unreachable_without_store(no_registry):
    ok, why = serving.registry_reachable()
    assert ok is False
    assert "MLFLOW_TRACKING_URI" in why  # honest, specific reason — not a silent skip


def test_registry_lookup_disabled_by_env(tmp_registry, monkeypatch):
    monkeypatch.setenv("MLFLOW_SERVING", "off")
    ok, why = serving.registry_reachable()
    assert ok is False
    assert "MLFLOW_SERVING=off" in why


# ── the champion path actually serves ────────────────────────────────────────

def test_champion_alias_is_resolved_at_serve_time(tmp_registry):
    """Register a champion, then resolve it the way startup does."""
    out = mt.log_lead_time_models(_results(), n_samples=3, n_features=1)
    assert out["champion"]["model_name"] == "random_forest"

    model, prov = serving.resolve_lead_time_champion()

    assert model is not None, "champion alias must resolve when a registry exists"
    assert prov["model_source"] == serving.SOURCE_MLFLOW
    assert prov["alias"] == mt.CHAMPION_ALIAS
    assert prov["registered_model"] == mt.LEAD_TIME_MODEL
    assert prov["model_version"] == str(out["champion"]["version"])
    assert prov["run_id"] == out["champion"]["run_id"]
    assert prov["fallback_reason"] is None
    # It is the WINNING estimator that got loaded, not just any of the four:
    # random_forest was fitted on constant 2.0.
    assert float(model.predict(np.array([[0.0]]))[0]) == pytest.approx(2.0)


def test_load_ml_state_prefers_champion_over_disk(tmp_registry, monkeypatch):
    """With a registry present, serving_model is the champion, not the joblib blob."""
    mt.log_lead_time_models(_results(), n_samples=3, n_features=1)

    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": ["f0"],
            "metrics": {"best_lead_time_model": "mlp", "current_stress_prob": 0.4},
        }.get(name),
    )

    state = serving.load_ml_state()
    assert state is not None
    assert state.provenance["model_source"] == serving.SOURCE_MLFLOW
    # Registry says random_forest won -> that label overrides the stale disk "mlp".
    assert state.best_lead_time_model == "random_forest"
    assert serving.get_serving_model(state) is state.serving_model
    assert float(state.serving_model.predict(np.array([[0.0]]))[0]) == pytest.approx(2.0)


# ── the fallback path is real and labelled ───────────────────────────────────

def test_load_ml_state_falls_back_to_joblib(no_registry, monkeypatch):
    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": ["f0"],
            "metrics": {"best_lead_time_model": "random_forest", "current_stress_prob": 0.4},
        }.get(name),
    )

    state = serving.load_ml_state()
    assert state is not None
    assert state.provenance["model_source"] == serving.SOURCE_JOBLIB
    assert state.provenance["fallback_reason"]           # must SAY why, never hide it
    assert state.provenance["model_uri"].endswith("lead_time.joblib")
    assert state.serving_model is disk["random_forest"]["model"]
    assert serving.model_source(state) == "local_joblib"


def test_get_serving_model_handles_missing_state():
    assert serving.get_serving_model(None) is None
    assert serving.model_source(None) == serving.SOURCE_NONE


def test_get_serving_model_falls_back_to_best_model_when_unset():
    """Legacy MLState (no serving_model) still resolves to the best estimator."""
    disk = _results()
    state = MLState(
        regime_model=None, regime_features=None, lead_time_models=disk,
        best_lead_time_model="random_forest", current_stress_prob=0.0,
        feature_columns=["f0"],
    )
    assert serving.get_serving_model(state) is disk["random_forest"]["model"]


# ── the API surfaces it ──────────────────────────────────────────────────────

def test_model_info_endpoint_reports_source(client, no_registry, monkeypatch):
    from app.ml import set_ml_state

    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": ["f0"],
            "metrics": {"best_lead_time_model": "random_forest", "current_stress_prob": 0.4},
        }.get(name),
    )
    set_ml_state(serving.load_ml_state())

    r = client.get("/api/v1/ml/model-info")
    assert r.status_code == 200
    body = r.json()
    assert body["model_source"] == "local_joblib"
    assert body["model_name"] == "random_forest"
    assert body["fallback_reason"]
    assert "MLflow champion alias was NOT used" in body["detail"]
