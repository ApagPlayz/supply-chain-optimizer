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
from app.ml import model_store


def _fitted_dummy():
    X = np.array([[0.0], [1.0], [2.0]])
    y = np.array([1.0, 2.0, 3.0])
    return DummyRegressor(strategy="mean").fit(X, y)


def _fake_results():
    """4 fake models with KNOWN rmse/cv_rmse_mean — random_forest is the clear winner.

    Champion selection now runs on ``cv_rmse_mean`` (repeated-split CV), not the
    single-split ``rmse``, so every model dict carries both — same ranking, kept
    intentionally distinct in value so a test that reads the wrong key fails loudly.
    """
    return {
        "ridge": {
            "model": _fitted_dummy(), "rmse": 5.0, "mae": 4.0, "r2": 0.50,
            "cv_rmse_mean": 5.2, "cv_rmse_std": 0.3, "cv_r2_mean": 0.48, "cv_r2_std": 0.05,
        },
        "random_forest": {
            "model": _fitted_dummy(), "rmse": 2.0, "mae": 1.5, "r2": 0.90,
            "cv_rmse_mean": 2.1, "cv_rmse_std": 0.2, "cv_r2_mean": 0.88, "cv_r2_std": 0.04,
        },
        "gradient_boosting": {
            "model": _fitted_dummy(), "rmse": 8.0, "mae": 6.0, "r2": 0.20,
            "cv_rmse_mean": 8.3, "cv_rmse_std": 0.4, "cv_r2_mean": 0.18, "cv_r2_std": 0.06,
        },
        "mlp": {
            "model": _fitted_dummy(), "rmse": 3.0, "mae": 2.5, "r2": 0.70,
            "cv_rmse_mean": 3.1, "cv_rmse_std": 0.25, "cv_r2_mean": 0.68, "cv_r2_std": 0.05,
        },
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


def test_champion_is_lowest_cv_rmse_run(tmp_tracking):
    # Champion selection runs on cv_rmse_mean (repeated-split CV), not the
    # single-split rmse — see mlflow_tracking.log_lead_time_models.
    out = mt.log_lead_time_models(_fake_results(), n_samples=3, n_features=1)
    champ = out["champion"]
    assert champ is not None
    assert champ["model_name"] == "random_forest"  # cv_rmse_mean 2.1 is the minimum
    assert champ["value"] == pytest.approx(2.1)
    assert champ["metric"] == "cv_rmse_mean"


def test_champion_alias_resolves_in_registry(tmp_tracking):
    from mlflow.tracking import MlflowClient

    out = mt.log_lead_time_models(_fake_results(), n_samples=3, n_features=1)
    champ = out["champion"]

    client = MlflowClient()
    mv = client.get_model_version_by_alias(mt.LEAD_TIME_MODEL, mt.CHAMPION_ALIAS)
    assert mv.version == champ["version"]
    assert mv.tags.get("selection_metric") == "cv_rmse_mean"


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


# ── champion selection must compare only runs from the SAME data panel ───────
#
# THE DEFECT (2026-09-03). `select_champion` ranked EVERY historical run on
# `cv_rmse_mean` and promoted the winner. But that metric is an absolute error
# **in days, on whatever rows the run saw** — it does not compare across data
# vintages. The weekly collector grew the lead-time panel from 1,879 usable rows
# / 263 features to 2,615 / 324; the new run scored 69.03 and the superseded run
# scored 68.80, so the OLD run "won" and the `champion` alias was re-pointed at a
# 263-feature estimator. Every serve-time call then raised
# `X has 324 features, but GradientBoostingRegressor is expecting 263`.
#
# The fixtures below reproduce exactly that shape: the STALE-panel run is given
# the better raw score, so a ranking that ignores the panel picks it. Against the
# old logic these tests fail; against the panel-restricted logic they pass.


def _panel(tmp_path, name: str, body: str):
    """A stand-in training panel — only its BYTES matter (they set the sha)."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _scored(**cv_rmse_mean: float):
    """`_fake_results()` with the CV score of each model overridden."""
    results = _fake_results()
    for name, value in cv_rmse_mean.items():
        results[name]["cv_rmse_mean"] = value
        results[name]["rmse"] = value  # keep both keys consistent
    return results


def test_champion_never_comes_from_a_run_on_a_different_panel(tmp_tracking, tmp_path):
    """A better score on a SUPERSEDED panel must not win. The regression test."""
    stale_panel = _panel(tmp_path, "panel_1879.csv", "old,panel\n1,2\n")
    current_panel = _panel(tmp_path, "panel_2615.csv", "new,panel\n1,2\n3,4\n")

    # Superseded vintage: every model here scores BETTER than anything on the
    # current panel — an easier population, not a better model.
    mt.log_lead_time_models(
        _scored(ridge=1.0, random_forest=1.1, gradient_boosting=1.2, mlp=1.3),
        n_samples=1879, n_features=263, training_data_path=stale_panel,
    )
    # Current vintage: random_forest is the best of these, and still worse than
    # every stale run.
    out = mt.log_lead_time_models(
        _scored(ridge=9.0, random_forest=5.0, gradient_boosting=6.0, mlp=7.0),
        n_samples=2615, n_features=324, training_data_path=current_panel,
    )

    champ = out["champion"]
    assert champ is not None
    assert champ["model_name"] == "random_forest", (
        "the champion came from a different data panel — cv_rmse_mean is an "
        "absolute error on the rows a run saw and does not rank across vintages"
    )
    assert champ["value"] == pytest.approx(5.0)
    assert champ["run_id"] == out["run_ids"]["random_forest"]
    assert champ["training_data_sha256"] == model_store.file_sha256(current_panel)
    # 4 current-panel runs were candidates; the 4 stale ones were excluded.
    assert champ["n_comparable_runs"] == 4


def test_the_alias_points_at_the_current_panel_run_not_the_better_stale_one(
    tmp_tracking, tmp_path
):
    """The registry ALIAS is what serving resolves — pin it, not just the return."""
    from mlflow.tracking import MlflowClient

    stale_panel = _panel(tmp_path, "stale.csv", "a\n1\n")
    current_panel = _panel(tmp_path, "current.csv", "a\n1\n2\n")

    mt.log_lead_time_models(
        _scored(ridge=1.0, random_forest=1.1, gradient_boosting=1.2, mlp=1.3),
        n_samples=1879, n_features=263, training_data_path=stale_panel,
    )
    out = mt.log_lead_time_models(
        _scored(ridge=9.0, random_forest=5.0, gradient_boosting=6.0, mlp=7.0),
        n_samples=2615, n_features=324, training_data_path=current_panel,
    )

    mv = MlflowClient().get_model_version_by_alias(mt.LEAD_TIME_MODEL, mt.CHAMPION_ALIAS)
    assert mv.run_id == out["run_ids"]["random_forest"]
    assert mv.tags.get(mt.TRAINING_DATA_SHA_PARAM) == model_store.file_sha256(current_panel)


def test_selection_refuses_when_no_run_saw_the_current_panel(tmp_tracking, tmp_path):
    """Nothing retrained yet -> promote NOTHING, loudly. Never a stale winner."""
    stale_panel = _panel(tmp_path, "stale.csv", "a\n1\n")
    current_panel = _panel(tmp_path, "current.csv", "a\n1\n2\n")

    mt.log_lead_time_models(
        _fake_results(), n_samples=1879, n_features=263,
        training_data_path=stale_panel, register_champion=False,
    )

    with pytest.raises(mt.IncomparableRunsError) as excinfo:
        mt.select_champion(
            mt.LEAD_TIME_EXPERIMENT, mt.LEAD_TIME_MODEL,
            metric=mt.LEAD_TIME_SELECTION_METRIC,
            require_data_sha=model_store.file_sha256(current_panel),
        )
    message = str(excinfo.value)
    assert "REFUSING" in message
    assert "seeds.train_ml_models" in message, "the error must say how to fix it"
    # It is a ValueError, so seeds/select_champion.py's handler still catches it.
    assert isinstance(excinfo.value, ValueError)


def test_a_run_with_no_recorded_panel_is_not_treated_as_comparable(tmp_tracking, tmp_path):
    """Runs logged before the panel stamp existed must not win by default.

    An unrecorded vintage is an UNKNOWN vintage. Treating "no sha" as "matches"
    would readmit exactly the runs this filter exists to exclude — the real
    backend/mlruns store is full of them.
    """
    current_panel = _panel(tmp_path, "current.csv", "a\n1\n2\n")

    mt.log_lead_time_models(          # no training_data_path -> no sha recorded
        _scored(ridge=0.1, random_forest=0.2, gradient_boosting=0.3, mlp=0.4),
        n_samples=1879, n_features=263, register_champion=False,
    )
    with pytest.raises(mt.IncomparableRunsError):
        mt.select_champion(
            mt.LEAD_TIME_EXPERIMENT, mt.LEAD_TIME_MODEL,
            metric=mt.LEAD_TIME_SELECTION_METRIC,
            require_data_sha=model_store.file_sha256(current_panel),
        )


def test_a_single_matching_run_wins_by_default(tmp_tracking, tmp_path):
    """Exactly one comparable run: it wins — there is nothing to rank it against.

    (There is no quality floor inside champion selection to apply here: the
    lead-time ship gate lives in `seeds/train_ml_models.py` and decides whether
    an artifact is persisted at all, before anything reaches the registry.)
    """
    stale_panel = _panel(tmp_path, "stale.csv", "a\n1\n")
    current_panel = _panel(tmp_path, "current.csv", "a\n1\n2\n")

    mt.log_lead_time_models(
        _scored(ridge=1.0, random_forest=1.1, gradient_boosting=1.2, mlp=1.3),
        n_samples=1879, n_features=263, training_data_path=stale_panel,
    )
    out = mt.log_lead_time_models(
        {"gradient_boosting": _fake_results()["gradient_boosting"]},
        n_samples=2615, n_features=324, training_data_path=current_panel,
    )
    champ = out["champion"]
    assert champ["model_name"] == "gradient_boosting"
    assert champ["n_comparable_runs"] == 1
    assert champ["training_data_sha256"] == model_store.file_sha256(current_panel)


def test_every_logged_run_records_the_panel_it_saw(tmp_tracking, tmp_path):
    """The stamp has to be on the NESTED runs — those are what selection ranks."""
    from mlflow.tracking import MlflowClient

    panel = _panel(tmp_path, "panel.csv", "a\n1\n")
    out = mt.log_lead_time_models(
        _fake_results(), n_samples=3, n_features=1, training_data_path=panel,
    )
    client = MlflowClient()
    expected = model_store.file_sha256(panel)
    for name, run_id in out["run_ids"].items():
        params = client.get_run(run_id).data.params
        assert params.get(mt.TRAINING_DATA_SHA_PARAM) == expected, (
            f"nested run {name} did not record its training panel"
        )
        assert params.get(mt.TRAINING_DATA_PATH_PARAM)
