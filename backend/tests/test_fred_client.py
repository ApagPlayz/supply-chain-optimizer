"""Tests for FRED feature engineering (no live API calls)."""
import pandas as pd
import pytest
from app.ml.fred_client import engineer_features, compute_stress_label, FRED_SERIES


def _make_fake_df() -> pd.DataFrame:
    """Build a minimal monthly DataFrame mimicking FRED output."""
    idx = pd.date_range("2020-01-01", periods=36, freq="MS")
    data = {
        "ppi_semis":       [100 + i * 0.5 for i in range(36)],
        "capacity_util":   [70 + (1 if i >= 18 else 0) * 6 for i in range(36)],
        "inventory_ratio": [1.40 - (0.1 if i >= 18 else 0) for i in range(36)],
        "industrial_prod": [150 + i * 0.3 for i in range(36)],
        "import_price":    [80 + i * 0.2 for i in range(36)],
        "freight_tsi":     [120 + i * 0.1 for i in range(36)],
    }
    return pd.DataFrame(data, index=idx)


def test_engineer_features_shape():
    df = _make_fake_df()
    features = engineer_features(df)
    # 6 series × 3 features = 18 columns
    assert features.shape[1] == 18


def test_engineer_features_no_nan():
    df = _make_fake_df()
    features = engineer_features(df)
    assert not features.isnull().any().any()


def test_engineer_features_column_names():
    df = _make_fake_df()
    features = engineer_features(df)
    for series_name in FRED_SERIES.keys():
        assert f"{series_name}_level" in features.columns
        assert f"{series_name}_mom3" in features.columns
        assert f"{series_name}_z12" in features.columns


def test_compute_stress_label_fires_on_threshold():
    df = _make_fake_df()
    # Months 18+ have capacity_util=76 and inventory_ratio=1.30 → stress=1
    labels = compute_stress_label(df)
    assert labels.iloc[:18].sum() == 0   # no stress in first 18 months
    assert labels.iloc[18:].sum() == 18  # all 18 remaining months are stress


def test_compute_stress_label_shape():
    df = _make_fake_df()
    labels = compute_stress_label(df)
    assert len(labels) == len(df)
