"""Regression tests for the train/serve feature-schema contract.

These are the two tests that were missing when the lead-time model silently
became a constant predictor (2026-08-15 audit, `docs/ML_API_PUSH_PLAN.md` item 1):

  CONTRACT — the column names AND order the serving path produces must be
             exactly the column names and order the training path produced.
             They had diverged (`cat_` vs `category_`, plus five serving-only
             features and two training-only ones) and `_align_row` zero-filled
             the difference instead of failing.

  VARIANCE — two materially different inputs must produce different predictions.
             Before the fix EVERY served prediction was 62.1085 days, because
             the served vector was the constant [0,0,0.9967,0,0,0,0,0,0].
             This test fails on the pre-fix code.

Both run against a model trained on the REAL observed panel, so they exercise
the same code path production serves rather than a mock.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.ml import model_store
from app.ml.lead_time_model import (
    CATEGORICAL_PREFIX,
    NUMERIC_PREFIX,
    NUMERIC_SPECS,
    align_row,
    build_design_matrix,
    build_feature_row,
    build_observed_matrix,
    known_categories,
    load_observed_panel,
    panel_to_records,
    parse_feature_cols,
    primary_category_feature,
    predict_lead_time,
    resolve_schema_from_records,
    retrain_lead_time,
)

PANEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "seeds" / "data" / "lead_time_panel" / "observed_lead_times.csv"
)


@pytest.fixture(scope="module")
def panel():
    df = load_observed_panel(PANEL_PATH)
    if df is None or len(df) < 30:
        pytest.skip("observed lead-time panel unavailable — nothing to pin")
    return df


@pytest.fixture(scope="module")
def trained(panel):
    """Train on the REAL panel. This is the object the contract is about."""
    out = retrain_lead_time(panel_path=PANEL_PATH)
    if out["status"] != "trained":
        pytest.skip(f"training skipped: {out.get('reason')}")
    return out


def _base_record(trained):
    """A REAL training record the resolved schema can encode.

    Synthesising a record by taking ``levels[0]`` of every categorical builds a
    combination that never occurs in the data — an impossible part. A linear
    model probed there extrapolates to a negative lead time, which the
    ``max(..., 1.0)`` floor clamps to a constant 1.0, and the variance tests then
    report a "constant predictor" that is really a fixture artefact. Probing a
    real point in the training distribution tests the property we actually care
    about.
    """
    records, _y, _g, _d, _c = panel_to_records(load_observed_panel(PANEL_PATH))
    cols = trained["feature_cols"]
    for record in records:
        try:
            align_row(record, cols)
        except Exception:
            continue
        return dict(record)
    pytest.skip("no training record can be encoded by the resolved schema")


def _serving_record(trained, **overrides):
    """A serving record for the resolved schema, based on a real part."""
    record = _base_record(trained)
    record.update(overrides)
    return build_feature_row(**record)


def _with_category(trained, category):
    """Vary the PRIMARY category feature, whichever one that currently is.

    ``known_categories()`` reports the vocabulary of the primary (refusing)
    categorical — ``dk_category`` today, ``category`` before DigiKey's taxonomy
    became canonical. Hardcoding the record key here meant this test silently
    varied a *secondary* feature and passed a constant predictor.
    """
    from app.ml.lead_time_model import CATEGORICAL_SPECS

    feature = primary_category_feature(trained["feature_cols"])
    assert feature is not None, "schema has no category feature to vary"
    return _serving_record(trained, **{CATEGORICAL_SPECS[feature].record_key: category})


# ── CONTRACT ─────────────────────────────────────────────────────────────────

def test_serving_columns_match_training_columns_exactly(trained):
    """THE contract: one schema, one order, both directions."""
    training_cols = trained["feature_cols"]
    _, serving_cols = build_design_matrix(
        [_serving_record(trained)], feature_cols=training_cols
    )
    assert serving_cols == training_cols, (
        "serving feature columns diverged from training columns:\n"
        f"  training: {training_cols}\n  serving:  {serving_cols}"
    )


def test_persisted_columns_round_trip_through_the_parser(trained):
    """Training emits columns; serving parses them back to the SAME schema."""
    cols = trained["feature_cols"]
    assert parse_feature_cols(cols).columns == cols


def test_serving_vector_width_matches_the_fitted_estimator(trained):
    """A width mismatch is how a zero-filled vector sneaks past sklearn."""
    cols = trained["feature_cols"]
    X = align_row(_serving_record(trained), cols)
    assert X.shape == (1, len(cols))
    for info in trained["models"].values():
        info["model"].predict(X)          # must not raise a feature-count error


def test_training_matrix_is_built_by_the_same_function_as_serving(panel):
    """build_observed_matrix must not have its own private encoder."""
    X_train, y_train, cols = build_observed_matrix(panel)
    records, y_all, groups, _dates, _counts = panel_to_records(panel)
    schema, _ = resolve_schema_from_records(records, snapshot_dates=_dates)
    assert schema.columns == cols

    # build_observed_matrix drops rows the schema cannot encode; reproduce that
    # drop here so the comparison is row-for-row.
    from app.ml.lead_time_model import _drop_unfillable
    kept, y_kept, _g, _n = _drop_unfillable(records, y_all, groups, schema)
    assert len(kept) == X_train.shape[0]
    np.testing.assert_allclose(y_kept, y_train, rtol=1e-9, atol=1e-9)

    # Every kept training row, rebuilt through the SERVING entrypoint, must be
    # bit-identical to the row training produced.
    for i in range(0, len(kept), max(1, len(kept) // 25)):
        np.testing.assert_allclose(
            align_row(kept[i], cols)[0], X_train[i], rtol=1e-9, atol=1e-9
        )


def test_every_column_is_a_declared_feature(trained):
    """No column may exist that the declarative spec does not account for."""
    schema = parse_feature_cols(trained["feature_cols"])
    for col in trained["feature_cols"]:
        assert col.startswith((NUMERIC_PREFIX, CATEGORICAL_PREFIX))
    assert set(schema.numerics) <= set(NUMERIC_SPECS)


def test_excluded_features_are_reported_not_silent(trained):
    """Every declared candidate is either in the schema or in the exclusion list."""
    from app.ml.lead_time_model import CATEGORICAL_SPECS
    schema = parse_feature_cols(trained["feature_cols"])
    included = set(schema.numerics) | {f for f, _ in schema.categoricals}
    excluded = {e["feature"] for e in trained["feature_exclusions"]}
    assert included | excluded == set(NUMERIC_SPECS) | set(CATEGORICAL_SPECS)
    assert not (included & excluded)
    for exclusion in trained["feature_exclusions"]:
        assert exclusion["reason"], f"{exclusion['feature']} excluded without a reason"


def test_persisted_artifacts_are_on_the_current_schema():
    """The committed joblib must not be a schema the code no longer builds."""
    cols = model_store.load("feature_cols")
    if not cols:
        pytest.skip("no persisted feature_cols — run `python -m seeds.train_ml_models`")
    parse_feature_cols(cols)   # raises FeatureSchemaMismatch if stale


# ── VARIANCE ─────────────────────────────────────────────────────────────────

def test_materially_different_inputs_give_different_predictions(trained):
    """FAILS on the pre-fix code, where every prediction was 62.1085 days."""
    cols = trained["feature_cols"]
    model = trained["models"][trained["best"]]["model"]
    cats = known_categories(cols)
    assert len(cats) >= 2, "need at least two trained categories to test variance"

    preds = {
        cat: predict_lead_time(model, _with_category(trained, cat), cols)
        for cat in cats
    }
    assert len({round(p, 4) for p in preds.values()}) > 1, (
        f"model returns the same value for every category: {preds}"
    )


def test_prediction_responds_to_the_numeric_features(trained):
    """The numeric block must actually move the output for some category."""
    cols = trained["feature_cols"]
    schema = parse_feature_cols(cols)
    if not schema.numerics:
        pytest.skip("no numeric features were admissible in this panel")
    model = trained["models"][trained["best"]]["model"]

    moved = False
    for cat in known_categories(cols):
        low = dict(_with_category(trained, cat))
        high = dict(low)
        # Perturb around the training median rather than to absurd extremes, so
        # a null result means "inert feature" and not "extrapolation clamp".
        for name in schema.numerics:
            key = NUMERIC_SPECS[name].record_key
            base = float(low[key])
            low[key] = max(base * 0.25, 0.0)
            high[key] = base * 4.0 + 1.0
        if abs(predict_lead_time(model, low, cols)
               - predict_lead_time(model, high, cols)) > 1e-6:
            moved = True
            break
    assert moved, "the numeric features change nothing — they are inert"


def test_every_estimator_in_the_bakeoff_varies(trained):
    """Not just the champion: a constant runner-up is also a broken pipeline."""
    cols = trained["feature_cols"]
    cats = known_categories(cols)
    for name, info in trained["models"].items():
        preds = [
            predict_lead_time(info["model"], _with_category(trained, c), cols)
            for c in cats
        ]
        assert len({round(p, 4) for p in preds}) > 1, (
            f"{name} predicts a constant {preds[0]} for all {len(cats)} categories"
        )
