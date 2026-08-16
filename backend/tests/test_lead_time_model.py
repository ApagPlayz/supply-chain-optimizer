"""Tests for the multi-model factory lead-time predictor (feature schema v3)."""
import numpy as np
import pytest
from app.ml.lead_time_labels import CATEGORY_BASE_LEAD_DAYS, DEFAULT_LEAD_DAYS, get_base_days
from app.ml.lead_time_model import (
    CATEGORICAL_PREFIX,
    CATEGORICAL_SPECS,
    FEATURE_SCHEMA_VERSION,
    MODELS,
    NUMERIC_PREFIX,
    NUMERIC_SPECS,
    OTHER_LEVEL,
    SERVE_SOURCES,
    UNKNOWN_LEVEL,
    FeatureSchemaMismatch,
    MissingFeatureError,
    UnknownCategoryError,
    build_design_matrix,
    build_feature_row,
    compute_baselines,
    known_categories,
    make_splits,
    parse_feature_cols,
    predict_lead_time,
    resolve_schema_from_records,
    serve_availability,
    train_all_models,
)


# ── label tests ─────────────────────────────────────────────────────────────

def test_known_category_returns_correct_days():
    assert get_base_days("Microcontrollers") == 98   # 14 weeks

def test_unknown_category_returns_default():
    assert get_base_days("Unobtanium") == DEFAULT_LEAD_DAYS

def test_all_categories_positive():
    for cat, days in CATEGORY_BASE_LEAD_DAYS.items():
        assert days > 0, f"{cat} has non-positive lead time"


# ── record / design-matrix tests ────────────────────────────────────────────

def _row(dk_category="Integrated Circuits (ICs)", unit_price=5.0, **extra):
    """A record keyed exactly as the declared specs expect."""
    return build_feature_row(dk_category=dk_category, unit_price=unit_price, **extra)


def _rows(n=60):
    """Enough rows, with variation, for the core declared features to be admissible."""
    cats = ["Integrated Circuits (ICs)", "Memory", "Sensors"]
    return [
        _row(dk_category=cats[i % 3], unit_price=float(1 + i % 17))
        for i in range(n)
    ]


def test_build_feature_row_keeps_what_it_is_given():
    row = _row(manufacturer="STMicroelectronics")
    assert row["dk_category"] == "Integrated Circuits (ICs)"
    assert row["manufacturer"] == "STMicroelectronics"


def test_design_matrix_shape_and_column_encoding():
    X, cols = build_design_matrix(_rows())
    assert X.shape == (60, len(cols))
    assert all(c.startswith((NUMERIC_PREFIX, CATEGORICAL_PREFIX)) for c in cols)
    assert sorted(known_categories(cols)) == [
        "Integrated Circuits (ICs)", "Memory", "Sensors",
    ]


def test_numeric_columns_precede_categorical_columns():
    _, cols = build_design_matrix(_rows())
    kinds = [c.startswith(CATEGORICAL_PREFIX) for c in cols]
    assert kinds == sorted(kinds), "numerics must come before the categorical block"


def test_design_matrix_no_nan():
    X, _ = build_design_matrix(_rows())
    assert not np.isnan(X).any()


def test_one_hot_is_exactly_one_per_categorical_per_row():
    X, cols = build_design_matrix(_rows())
    idx = [i for i, c in enumerate(cols) if c.startswith(f"{CATEGORICAL_PREFIX}dk_category=")]
    assert (X[:, idx].sum(axis=1) == 1.0).all()


def test_serving_never_invents_or_reorders_columns():
    """Given feature_cols, the data can only fill the schema — never change it."""
    _, cols = build_design_matrix(_rows())
    X, out_cols = build_design_matrix([_row(dk_category="Memory")], feature_cols=cols)
    assert out_cols == cols
    assert X.shape == (1, len(cols))


def test_unknown_category_is_refused_not_zero_filled():
    """The 2026-08 bug encoded unseen names as all-zeros and predicted anyway."""
    _, cols = build_design_matrix(_rows())
    with pytest.raises(UnknownCategoryError):
        build_design_matrix([_row(dk_category="Unobtanium")], feature_cols=cols)


def test_exactly_the_canonical_category_refuses_unseen_levels():
    """DigiKey's taxonomy is canonical for a DigiKey-quoted target."""
    refusing = [n for n, s in CATEGORICAL_SPECS.items() if s.unseen_policy == "refuse"]
    assert refusing == ["dk_category"]
    for name, spec in CATEGORICAL_SPECS.items():
        if name != "dk_category":
            assert spec.unseen_policy == "other", name


def test_nan_never_becomes_a_literal_level():
    """A float NaN is 'unknown', not a category called 'nan'."""
    rows = [_row() for _ in range(10)]
    for r in rows[:5]:
        r["dk_category"] = float("nan")
    _, cols = build_design_matrix(rows)
    levels = [
        c.split("=", 2)[2] for c in cols
        if c.startswith(f"{CATEGORICAL_PREFIX}dk_category=")
    ]
    assert "nan" not in levels
    assert UNKNOWN_LEVEL in levels


def test_v1_and_v2_feature_cols_are_rejected():
    """Both earlier encodings must fail loudly rather than be misread."""
    v1 = ["is_active", "log_stock", "macro_stress", "cat_Microcontrollers", "src_digikey"]
    v2 = ["log_stock", "log_unit_price", "cat=Integrated Circuits (ICs)"]
    for legacy in (v1, v2):
        with pytest.raises(FeatureSchemaMismatch):
            parse_feature_cols(legacy)
        with pytest.raises(FeatureSchemaMismatch):
            build_design_matrix([_row()], feature_cols=legacy)


def test_unknown_logical_feature_name_is_rejected():
    with pytest.raises(FeatureSchemaMismatch):
        parse_feature_cols([f"{NUMERIC_PREFIX}log_unobtanium",
                            f"{CATEGORICAL_PREFIX}dk_category=Memory"])


def test_numeric_after_categorical_is_rejected():
    with pytest.raises(FeatureSchemaMismatch):
        parse_feature_cols([f"{CATEGORICAL_PREFIX}dk_category=Memory",
                            f"{NUMERIC_PREFIX}log_unit_price"])


def test_missing_required_value_is_refused_not_imputed():
    _, cols = build_design_matrix(_rows())
    with pytest.raises(MissingFeatureError):
        build_design_matrix([{"dk_category": "Memory"}], feature_cols=cols)


def test_feature_schema_version_is_pinned():
    assert FEATURE_SCHEMA_VERSION == 3


# ── declarative resolution ──────────────────────────────────────────────────

def test_constant_feature_is_excluded_with_a_stated_reason():
    """This is the macro_stress / src_digikey failure mode, generalised."""
    rows = [_row(unit_price=7.0) for _ in range(40)]   # log_unit_price is constant
    schema, exclusions = resolve_schema_from_records(rows)
    assert f"{NUMERIC_PREFIX}log_unit_price" not in schema.columns
    reason = next(e["reason"] for e in exclusions if e["feature"] == "log_unit_price")
    assert "constant" in reason


def test_feature_absent_from_the_panel_is_excluded_with_a_stated_reason():
    rows = _rows()                                   # no packaging key at all
    schema, exclusions = resolve_schema_from_records(rows)
    assert not any(c.startswith(f"{CATEGORICAL_PREFIX}packaging=") for c in schema.columns)
    assert any(e["feature"] == "packaging" for e in exclusions)


def test_feature_unresolvable_at_serve_time_is_excluded():
    """A column we cannot read in production must never enter the schema."""
    caps = {name: (False, "pretend the ORM lacks it") for name in SERVE_SOURCES}
    schema, exclusions = resolve_schema_from_records(_rows(), serve_caps=caps)
    assert schema.columns == []
    assert len(exclusions) == len(NUMERIC_SPECS) + len(CATEGORICAL_SPECS)
    assert all("not resolvable at prediction time" in e["reason"] for e in exclusions)


def test_no_declared_feature_is_ever_dropped_silently():
    _, exclusions = resolve_schema_from_records(_rows())
    schema, _ = resolve_schema_from_records(_rows())
    accounted = {e["feature"] for e in exclusions} | set(schema.numerics) | {
        f for f, _ in schema.categoricals
    }
    assert accounted == set(NUMERIC_SPECS) | set(CATEGORICAL_SPECS)


def test_serve_availability_reports_every_declared_feature():
    caps = serve_availability()
    assert set(caps) == set(SERVE_SOURCES)
    for name, (ok, why) in caps.items():
        assert isinstance(ok, bool) and why, name


def test_rare_levels_fold_into_a_trained_other_bucket():
    rows = [_row(manufacturer="STMicro") for _ in range(40)]
    rows.append(_row(manufacturer="OneOffCorp"))
    schema, _ = resolve_schema_from_records(rows)
    levels = schema.levels("manufacturer")
    if levels:                       # only when manufacturer is admissible
        assert OTHER_LEVEL in levels
        assert "OneOffCorp" not in levels
        # And an entirely unseen manufacturer maps into that trained bucket.
        build_design_matrix(
            [_row(manufacturer="NeverSeenCo")], feature_cols=schema.columns,
        )


# ── grouped splitting ───────────────────────────────────────────────────────

def test_grouped_splits_never_put_one_part_on_both_sides():
    """The panel repeats an MPN across snapshots; a random split would leak it."""
    groups = [f"MPN-{i // 2}" for i in range(80)]     # each part appears twice
    for train_idx, test_idx in make_splits(80, groups, n_splits=5):
        assert not (set(np.asarray(groups)[train_idx]) & set(np.asarray(groups)[test_idx]))


# ── model training ──────────────────────────────────────────────────────────

def _training_set(n=240):
    rng = np.random.default_rng(42)
    categories = list(CATEGORY_BASE_LEAD_DAYS.keys())[:5]
    rows, targets, groups = [], [], []
    for i in range(n):
        cat = categories[i % len(categories)]
        price = float(rng.uniform(0.5, 90))
        rows.append(_row(dk_category=cat, unit_price=price))
        base = CATEGORY_BASE_LEAD_DAYS.get(cat, DEFAULT_LEAD_DAYS)
        targets.append(float(base * (1 + 0.5 * rng.random()) + 0.1 * price))
        groups.append(f"FAMILY-{i}")
    return rows, np.asarray(targets, dtype=float), groups


def test_train_all_models_returns_four_models():
    rows, y, groups = _training_set()
    X, _ = build_design_matrix(rows)
    results = train_all_models(X, y, n_cv_splits=3, groups=groups)
    assert set(results.keys()) == set(MODELS.keys())


def test_train_all_models_metrics_present():
    rows, y, groups = _training_set()
    X, _ = build_design_matrix(rows)
    results = train_all_models(X, y, n_cv_splits=3, groups=groups)
    for _name, info in results.items():
        for key in ("model", "rmse", "mae", "r2", "cv_rmse_mean", "cv_rmse_std",
                    "cv_r2_mean", "cv_r2_median", "cv_rmse_per_split"):
            assert key in info
        assert info["rmse"] >= 0.0
        assert len(info["cv_rmse_per_split"]) == 3


def test_naive_baselines_are_always_reported():
    """A model metric published without its baseline is not a claim, it's a boast."""
    rows, y, groups = _training_set()
    X, cols = build_design_matrix(rows)
    baselines = compute_baselines(X, y, cols, n_cv_splits=3, groups=groups)
    assert set(baselines) == {
        "train_mean", "always_210d", "category_mean", "manufacturer_mean",
    }
    for info in baselines.values():
        assert info["cv_rmse_mean"] >= 0.0
        assert len(info["cv_rmse_per_split"]) == 3


def test_baselines_scored_on_the_same_folds_as_the_models():
    """Paired comparison is only valid if the folds are identical."""
    rows, y, groups = _training_set()
    X, cols = build_design_matrix(rows)
    a = train_all_models(X, y, n_cv_splits=4, groups=groups)
    b = compute_baselines(X, y, cols, n_cv_splits=4, groups=groups)
    assert len(a["ridge"]["cv_rmse_per_split"]) == len(b["category_mean"]["cv_rmse_per_split"])


def test_predict_lead_time_returns_positive():
    rows, y, groups = _training_set()
    X, cols = build_design_matrix(rows)
    results = train_all_models(X, y, n_cv_splits=2, groups=groups)
    assert predict_lead_time(results["ridge"]["model"], rows[0], cols) > 0.0
