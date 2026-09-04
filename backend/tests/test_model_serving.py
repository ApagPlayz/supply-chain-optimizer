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


#: How wide a fixture model is. It MUST equal ``len(_VALID_FEATURE_COLS)``:
#: ``load_ml_state`` now refuses a champion whose input width disagrees with the
#: persisted feature schema (that mismatch is the 2026-09-03 defect), so a
#: 1-column dummy paired with a 3-column schema would be modelling the broken
#: state, not the working one.
_N_FIXTURE_FEATURES = 3


def _fitted_dummy(constant: float, n_features: int = _N_FIXTURE_FEATURES) -> DummyRegressor:
    X = np.zeros((3, n_features))
    y = np.array([constant, constant, constant])
    return DummyRegressor(strategy="mean").fit(X, y)


def _row(n_features: int = _N_FIXTURE_FEATURES) -> np.ndarray:
    """One inference row of the fixture width (DummyRegressor still checks it)."""
    return np.zeros((1, n_features))


def _results():
    """4 models with known RMSE/cv_rmse_mean — random_forest wins on both.

    Champion selection runs on cv_rmse_mean (see mlflow_tracking.log_lead_time_models),
    so every model dict carries it alongside the single-split rmse.
    """
    return {
        "ridge": {
            "model": _fitted_dummy(1.0), "rmse": 5.0, "mae": 4.0, "r2": 0.50,
            "cv_rmse_mean": 5.2, "cv_rmse_std": 0.3, "cv_r2_mean": 0.48, "cv_r2_std": 0.05,
        },
        "random_forest": {
            "model": _fitted_dummy(2.0), "rmse": 2.0, "mae": 1.5, "r2": 0.90,
            "cv_rmse_mean": 2.1, "cv_rmse_std": 0.2, "cv_r2_mean": 0.88, "cv_r2_std": 0.04,
        },
        "gradient_boosting": {
            "model": _fitted_dummy(3.0), "rmse": 8.0, "mae": 6.0, "r2": 0.20,
            "cv_rmse_mean": 8.3, "cv_rmse_std": 0.4, "cv_r2_mean": 0.18, "cv_r2_std": 0.06,
        },
        "mlp": {
            "model": _fitted_dummy(4.0), "rmse": 3.0, "mae": 2.5, "r2": 0.70,
            "cv_rmse_mean": 3.1, "cv_rmse_std": 0.25, "cv_r2_mean": 0.68, "cv_r2_std": 0.05,
        },
    }


#: A minimal valid v3 feature schema (see app/ml/lead_time_model.py). Placeholder
#: names like "f0" are rejected by validate_feature_cols/_check_feature_schema.
def _valid_feature_cols():
    """A minimal CURRENT-schema column list, derived from the declared specs.

    Built from `app.ml.lead_time_model` rather than hardcoded, so this fixture
    cannot silently rot into the very stale-schema state that `load_ml_state`
    now refuses to serve — which is exactly what these tests are checking.
    """
    from app.ml.lead_time_model import (
        CATEGORICAL_PREFIX,
        NUMERIC_PREFIX,
        NUMERIC_SPECS,
        validate_feature_cols,
    )
    numeric = sorted(NUMERIC_SPECS)[0]
    cols = [
        f"{NUMERIC_PREFIX}{numeric}",
        f"{CATEGORICAL_PREFIX}dk_category=Integrated Circuits (ICs)",
        f"{CATEGORICAL_PREFIX}dk_category=Memory",
    ]
    validate_feature_cols(cols)   # fail loudly here, not deep inside a serving test
    return cols


_VALID_FEATURE_COLS = _valid_feature_cols()


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
    assert float(model.predict(_row())[0]) == pytest.approx(2.0)


def test_load_ml_state_prefers_champion_over_disk(tmp_registry, monkeypatch):
    """With a registry present, serving_model is the champion, not the joblib blob."""
    mt.log_lead_time_models(_results(), n_samples=3, n_features=1)

    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": _VALID_FEATURE_COLS,
            "metrics": {"best_lead_time_model": "mlp", "current_stress_prob": 0.4},
        }.get(name),
    )

    state = serving.load_ml_state()
    assert state is not None
    assert state.provenance["model_source"] == serving.SOURCE_MLFLOW
    # Registry says random_forest won -> that label overrides the stale disk "mlp".
    assert state.best_lead_time_model == "random_forest"
    assert serving.get_serving_model(state) is state.serving_model
    assert float(state.serving_model.predict(_row())[0]) == pytest.approx(2.0)


def test_a_champion_fitted_on_a_different_panel_is_refused_not_served(
    tmp_registry, monkeypatch
):
    """A narrower champion must be REFUSED at startup, not crash on request 1.

    THE INCIDENT (2026-09-03). The `champion` alias pointed at a run trained on
    the previous panel — 263 features where this code now builds 324 — because
    champion selection ranked runs across data vintages. Nothing noticed until a
    prediction was attempted, and the answer was sklearn's
    `X has 324 features, but GradientBoostingRegressor is expecting 263`: a 500
    naming no artifact, no run and no remedy.

    Here the registry deliberately holds a champion of the wrong width. Startup
    must decline it, say why on the provenance the API publishes, and serve the
    committed on-disk model instead — refusing a model is not having none.
    """
    narrow = _results()
    for info in narrow.values():
        info["model"] = _fitted_dummy(9.0, n_features=_N_FIXTURE_FEATURES - 1)
    mt.log_lead_time_models(narrow, n_samples=3, n_features=_N_FIXTURE_FEATURES - 1)

    disk = _results()  # the current-panel artifact, correct width
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": _VALID_FEATURE_COLS,
            "metrics": {"best_lead_time_model": "random_forest", "current_stress_prob": 0.4},
        }.get(name),
    )

    state = serving.load_ml_state()
    assert state is not None
    assert state.provenance["model_source"] == serving.SOURCE_JOBLIB
    reason = state.provenance["fallback_reason"]
    assert "REFUSED" in reason and str(len(_VALID_FEATURE_COLS)) in reason
    assert state.serving_model is disk["random_forest"]["model"]
    # ...and it can actually answer, which the 263-feature champion could not.
    assert float(serving.get_serving_model(state).predict(_row())[0]) == pytest.approx(2.0)


def test_feature_width_check_stays_silent_when_it_cannot_compare():
    """No persisted schema, or an estimator with no recorded width => no verdict.

    Inventing a mismatch from missing information would fail closed on artifacts
    that are merely undocumented.
    """
    model = _fitted_dummy(1.0)
    assert serving.champion_feature_width_mismatch(model, _VALID_FEATURE_COLS) is None
    assert serving.champion_feature_width_mismatch(model, []) is None
    assert serving.champion_feature_width_mismatch(object(), _VALID_FEATURE_COLS) is None


# ── the fallback path is real and labelled ───────────────────────────────────

def test_load_ml_state_falls_back_to_joblib(no_registry, monkeypatch):
    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": _VALID_FEATURE_COLS,
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


# ── model_version on the local_joblib path (the ONLY path used in production) ─
# Regression test: this used to be hardcoded None (see docstring of
# app.ml.serving._artifact_provenance history) so GET /ml/model-info and
# GET /ml/lead-time always reported "VERSION —" in production, even though the
# artifact's fit-time provenance (metrics.joblib["provenance"]) already records
# a git sha and a training date that can stand in for a real version string.

def test_derive_model_version_prefers_short_git_sha():
    version = serving._derive_model_version(
        {"git_sha": "3958e87a13adf4a3cafaa85385ac306faf690d3b-dirty", "trained_at": "2026-08-17T10:09:06+00:00"}
    )
    assert version == "3958e87-dirty"


def test_derive_model_version_clean_sha_has_no_dirty_suffix():
    version = serving._derive_model_version({"git_sha": "3958e87a13adf4a3cafaa85385ac306faf690d3b"})
    assert version == "3958e87"


def test_derive_model_version_falls_back_to_trained_at_date():
    version = serving._derive_model_version({"trained_at": "2026-08-17T10:09:06+00:00"})
    assert version == "2026-08-17"


def test_derive_model_version_none_when_no_provenance():
    assert serving._derive_model_version(None) is None
    assert serving._derive_model_version({}) is None


def test_load_ml_state_joblib_path_surfaces_real_model_version(no_registry, monkeypatch):
    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": _VALID_FEATURE_COLS,
            "metrics": {
                "best_lead_time_model": "random_forest",
                "current_stress_prob": 0.4,
                "provenance": {
                    "git_sha": "3958e87a13adf4a3cafaa85385ac306faf690d3b-dirty",
                    "trained_at": "2026-08-17T10:09:06+00:00",
                },
            },
        }.get(name),
    )

    state = serving.load_ml_state()
    assert state is not None
    assert state.provenance["model_source"] == serving.SOURCE_JOBLIB
    assert state.provenance["model_version"] == "3958e87-dirty"  # NOT None


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


def test_model_info_endpoint_reports_real_model_version_on_joblib_path(
    client, no_registry, monkeypatch
):
    """GET /ml/model-info is the ONLY path used in production (no MLflow server
    on the Render free tier), and used to always report model_version=None
    there -> the Model Card rendered "VERSION —". It must now report the
    artifact's real fit-time provenance instead.
    """
    from app.ml import set_ml_state

    disk = _results()
    monkeypatch.setattr(serving.model_store, "models_exist", lambda: True)
    monkeypatch.setattr(
        serving.model_store, "load",
        lambda name: {
            "lead_time": disk,
            "feature_cols": ["f0"],
            "metrics": {
                "best_lead_time_model": "random_forest",
                "current_stress_prob": 0.4,
                "provenance": {"git_sha": "3958e87a13adf4a3cafaa85385ac306faf690d3b-dirty"},
            },
        }.get(name),
    )
    set_ml_state(serving.load_ml_state())

    r = client.get("/api/v1/ml/model-info")
    assert r.status_code == 200
    assert r.json()["model_version"] == "3958e87-dirty"


# ── /ml/stress publishes shortage_recall (backend/app/api/ml.py) ──────────────
# Regression test: StressResponse declared shortage_recall but no branch of
# GET /ml/stress ever set it, so it was always null and the Model Card rendered
# "—". The real value lives in metrics.joblib["regime"]["shortage_recall"]
# (recall on the STRESS class specifically), which resolve_regime_signal already
# carries through into MLState.regime_status["metrics"] verbatim.

def test_stress_endpoint_surfaces_shortage_recall_when_available(client):
    from app.ml import set_ml_state
    from app.ml import MLState as _MLState

    state = _MLState(
        regime_model=object(),   # only needs to be non-None; endpoint checks `is not None`
        regime_features=None,
        lead_time_models={},
        best_lead_time_model=None,
        current_stress_prob=0.42,
        feature_columns=[],
        regime_status={
            "available": True,
            "ship_gate": {"policy": "brier", "reason": "beats persistence on Brier score"},
            "metrics": {"shortage_recall": 0.7018, "log_loss": 0.7353},
        },
    )
    set_ml_state(state)

    r = client.get("/api/v1/ml/stress")
    assert r.status_code == 200
    assert r.json()["shortage_recall"] == pytest.approx(0.7018)


def test_stress_endpoint_shortage_recall_none_when_unavailable(client):
    """The gate-failed / no-artifact branch must not raise trying to read a
    missing key — it degrades to None like every other optional metric here."""
    from app.ml import set_ml_state
    from app.ml import MLState as _MLState

    state = _MLState(
        regime_model=None,
        regime_features=None,
        lead_time_models={},
        best_lead_time_model=None,
        current_stress_prob=0.0,
        feature_columns=[],
        regime_status={
            "available": False,
            "reason": "no artifact",
            "source": "unavailable_no_artifact",
            "ship_gate": {},
            "metrics": {},
        },
    )
    set_ml_state(state)

    r = client.get("/api/v1/ml/stress")
    assert r.status_code == 200
    assert r.json()["shortage_recall"] is None
