"""Tests for multi-model lead time predictor."""
import numpy as np
import pytest
from app.ml.lead_time_labels import CATEGORY_BASE_LEAD_DAYS, DEFAULT_LEAD_DAYS, get_base_days
from app.ml.lead_time_model import (
    build_feature_row,
    build_training_matrix,
    train_all_models,
    predict_lead_time,
    MODELS,
)


# ── label tests ─────────────────────────────────────────────────────────────

def test_known_category_returns_correct_days():
    assert get_base_days("Microcontrollers") == 98   # 14 weeks

def test_unknown_category_returns_default():
    assert get_base_days("Unobtanium") == DEFAULT_LEAD_DAYS

def test_all_categories_positive():
    for cat, days in CATEGORY_BASE_LEAD_DAYS.items():
        assert days > 0, f"{cat} has non-positive lead time"


# ── feature / training matrix tests ─────────────────────────────────────────

def _fake_row():
    return build_feature_row(
        category="Microcontrollers",
        is_domestic=True,
        dist_km=500.0,
        tier="major",
        macro_stress=0.2,
        risk_score=0.4,
        stock_coverage=20.0,
        is_chinese_origin=False,
    )

def test_build_feature_row_returns_dict():
    row = _fake_row()
    assert isinstance(row, dict)
    assert "is_domestic" in row
    assert "dist_km" in row
    assert "macro_stress" in row

def test_build_training_matrix_shape():
    rows = [_fake_row() for _ in range(100)]
    targets = [float(i + 50) for i in range(100)]
    X, y, cols = build_training_matrix(rows, targets)
    assert X.shape[0] == 100
    assert len(y) == 100
    assert X.shape[1] == len(cols)

def test_build_training_matrix_no_nan():
    rows = [_fake_row() for _ in range(50)]
    targets = [70.0] * 50
    X, y, cols = build_training_matrix(rows, targets)
    assert not np.isnan(X).any()
    assert not np.isnan(y).any()


# ── model training tests ─────────────────────────────────────────────────────

def _small_training_set():
    np.random.seed(42)
    rows = []
    targets = []
    categories = list(CATEGORY_BASE_LEAD_DAYS.keys())[:5]
    for i in range(200):
        cat = categories[i % len(categories)]
        row = build_feature_row(
            category=cat,
            is_domestic=bool(i % 2),
            dist_km=float(np.random.uniform(100, 15000)),
            tier=["major", "mid", "broker"][i % 3],
            macro_stress=float(np.random.uniform(0, 0.8)),
            risk_score=float(np.random.uniform(0.1, 0.9)),
            stock_coverage=float(np.random.uniform(1, 50)),
            is_chinese_origin=bool(i % 3 == 0),
        )
        rows.append(row)
        base = CATEGORY_BASE_LEAD_DAYS.get(cat, DEFAULT_LEAD_DAYS)
        targets.append(float(base * (1 + 0.5 * np.random.random())))
    return rows, targets

def test_train_all_models_returns_four_models():
    rows, targets = _small_training_set()
    X, y, cols = build_training_matrix(rows, targets)
    results = train_all_models(X, y)
    assert set(results.keys()) == set(MODELS.keys())

def test_train_all_models_metrics_present():
    rows, targets = _small_training_set()
    X, y, cols = build_training_matrix(rows, targets)
    results = train_all_models(X, y)
    for name, info in results.items():
        assert "model" in info
        assert "rmse" in info
        assert "mae" in info
        assert "r2" in info
        assert info["rmse"] >= 0.0

def test_predict_lead_time_returns_positive():
    rows, targets = _small_training_set()
    X, y, cols = build_training_matrix(rows, targets)
    results = train_all_models(X, y)
    row = _fake_row()
    pred = predict_lead_time(results["ridge"]["model"], row, cols)
    assert pred > 0.0
