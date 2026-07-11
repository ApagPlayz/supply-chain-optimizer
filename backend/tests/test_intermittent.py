"""Unit tests for intermittent-demand estimators + scaled-error metrics.

Fast and fully offline — no data download (that path is exercised by the
seeds.run_carparts_backtest script). Pins the mathematical contracts of
Croston / SBA / TSB and MASE / RMSSE.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.ml.intermittent import croston, mase, naive_last, rmsse, sba, tsb

# A canonical intermittent series: mostly zeros, sporadic small demands.
INTERMITTENT = [0, 0, 2, 0, 0, 0, 1, 0, 0, 3, 0, 0, 0, 1, 0, 0]


def test_all_methods_return_flat_horizon():
    for fn in (croston, sba, tsb):
        out = fn(INTERMITTENT, horizon=12)
        assert len(out) == 12
        assert all(v == out[0] for v in out)      # constant rate forecast
        assert out[0] >= 0.0


def test_croston_rate_is_positive_for_nonzero_series():
    rate = croston(INTERMITTENT, horizon=1)[0]
    # 7 total demand over 16 periods ≈ 0.44/period; Croston rate should be in range.
    assert 0.1 < rate < 1.5


def test_sba_is_below_croston_by_bias_factor():
    """SBA = Croston * (1 - alpha/2). With alpha=0.1 that's a 5% haircut."""
    c = croston(INTERMITTENT, horizon=1, alpha=0.1)[0]
    s = sba(INTERMITTENT, horizon=1, alpha=0.1)[0]
    assert s == pytest.approx(c * 0.95)


def test_all_zero_series_forecasts_zero():
    zeros = [0.0] * 20
    assert croston(zeros, 5) == [0.0] * 5
    assert sba(zeros, 5) == [0.0] * 5
    assert tsb(zeros, 5) == [0.0] * 5


def test_tsb_decays_toward_zero_when_demand_stops():
    """A SKU that goes obsolete: TSB rate should be well below its early rate."""
    active_then_dead = [3, 2, 4, 3] + [0] * 20
    rate = tsb(active_then_dead, horizon=1)[0]
    early_rate = tsb([3, 2, 4, 3], horizon=1)[0]
    assert rate < early_rate


def test_naive_last_repeats_last_value():
    assert naive_last([1, 2, 5], 3) == [5.0, 5.0, 5.0]


def test_mase_zero_when_perfect():
    train = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert mase(train, [6.0], [6.0], seasonality=1) == 0.0


def test_mase_nan_when_naive_denominator_zero():
    flat = [5.0] * 6      # seasonal-naive one-step error is 0 → undefined
    assert math.isnan(mase(flat, [5.0], [4.0], seasonality=1))


def test_rmsse_scales_by_insample_naive():
    train = [0.0, 1.0, 0.0, 1.0, 0.0]     # in-sample naive MSE = 1.0
    val = rmsse(train, [0.0, 0.0], [1.0, 1.0])  # test MSE = 1.0 → RMSSE = 1.0
    assert val == pytest.approx(1.0)


def test_rmsse_nan_when_constant_train():
    assert math.isnan(rmsse([2.0, 2.0, 2.0], [2.0], [3.0]))
