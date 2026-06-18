"""Tests for forecast metrics and the walk-forward backtest harness (P1)."""
import math

import pytest

from app.ml import forecast_metrics as fm
from app.ml.backtest import walk_forward_backtest


# ── Metrics ──────────────────────────────────────────────────────────────────

def test_perfect_forecast_is_zero_error():
    a = [10.0, 20.0, 30.0, 40.0]
    assert fm.wape(a, a) == 0.0
    assert fm.mape(a, a) == 0.0
    assert fm.rmse(a, a) == 0.0
    assert fm.bias(a, a) == 0.0
    assert fm.tracking_signal(a, a) == 0.0


def test_wape_is_total_abs_error_over_total_actual():
    actuals = [100.0, 100.0]
    forecasts = [110.0, 90.0]   # errors +10, -10 → Σ|err|=20, Σ|a|=200
    assert fm.wape(actuals, forecasts) == pytest.approx(0.1)


def test_bias_detects_systematic_over_forecast():
    actuals = [50.0, 60.0, 70.0]
    forecasts = [55.0, 65.0, 75.0]   # always +5
    assert fm.bias(actuals, forecasts) == pytest.approx(5.0)
    # Tracking signal should be strongly positive (all error same sign).
    assert fm.tracking_signal(actuals, forecasts) > 0


def test_wape_zero_actual_guard():
    # All-zero actuals with non-zero forecast → inf (undefined %), not a crash.
    assert math.isinf(fm.wape([0.0, 0.0], [1.0, 2.0]))
    # All-zero actuals and forecast → defined as 0.
    assert fm.wape([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        fm.rmse([1.0, 2.0], [1.0])


# ── Walk-forward backtest ────────────────────────────────────────────────────

def test_backtest_perfect_model_zero_error():
    # Series of length 24; predict the actual values exactly via a clairvoyant model.
    series = [float(i) for i in range(24)]

    def clairvoyant(train):
        start = len(train)
        return [float(start + h) for h in range(4)]

    report = walk_forward_backtest(series, clairvoyant, horizon=4, n_windows=3)
    assert report.n_windows == 3
    assert report.horizon == 4
    assert len(report.per_horizon) == 4
    assert report.overall.wape == 0.0
    assert report.overall.rmse == 0.0
    # Three non-overlapping windows → train sizes grow by one horizon each.
    assert report.train_sizes == [12, 16, 20]


def test_backtest_buckets_errors_by_horizon():
    # A naive "repeat last value" model degrades as horizon grows on a trend.
    series = [float(i) for i in range(40)]

    def naive_last(train):
        last = train[-1]
        return [last] * 6  # flat forecast — error grows with horizon on a trend

    report = walk_forward_backtest(series, naive_last, horizon=6, n_windows=3)
    rmses = [h.rmse for h in report.per_horizon]
    # Later horizons should have larger error than the first horizon.
    assert rmses[-1] > rmses[0]
    # Horizon labels are 1-indexed and ordered.
    assert [h.horizon for h in report.per_horizon] == [1, 2, 3, 4, 5, 6]


def test_backtest_raises_when_series_too_short():
    series = [1.0] * 10
    with pytest.raises(ValueError):
        walk_forward_backtest(series, lambda t: [0.0] * 12, horizon=12, n_windows=3)


def test_backtest_rejects_wrong_prediction_length():
    series = [float(i) for i in range(24)]
    with pytest.raises(ValueError):
        walk_forward_backtest(series, lambda t: [0.0, 0.0], horizon=4, n_windows=3)


def test_report_serializes_to_dict():
    series = [float(i) for i in range(24)]
    report = walk_forward_backtest(series, lambda t: [float(len(t))] * 4, horizon=4, n_windows=3)
    d = report.as_dict()
    assert d["method"] == "walk_forward_rolling_origin"
    assert d["n_windows"] == 3
    assert len(d["by_horizon"]) == 4
    assert set(d["overall"]) >= {"wape", "mape", "rmse", "bias", "tracking_signal"}
