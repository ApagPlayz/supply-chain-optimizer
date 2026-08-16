"""Unit tests for intermittent-demand estimators + scaled-error metrics.

Fast and fully offline — no data download (that path is exercised by the
seeds.run_carparts_backtest script). Pins the mathematical contracts of
Croston / SBA / TSB and MASE / RMSSE, and of their predictive-distribution twins:
that each distribution has the SAME mean as its point forecast, that P(Y=0)
equals 1 - p under the compound-Bernoulli parameterisation, and that a degenerate
distribution's scaled CRPS is exactly its MASE.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.ml.intermittent import (
    climatology_dist,
    croston,
    croston_dist,
    mase,
    mase_denominator,
    naive_last,
    naive_last_dist,
    point_mass,
    rmsse,
    sba,
    sba_dist,
    scaled_crps,
    scaled_pinball,
    tsb,
    tsb_dist,
    zero_dist,
)

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


# ─────────────────────────────────────────────────────────────────────────────
# Predictive distributions
# ─────────────────────────────────────────────────────────────────────────────

ALPHA = 0.1
DIST_FNS = (croston_dist, sba_dist, tsb_dist, naive_last_dist, zero_dist, climatology_dist)


def _mean(pmf) -> float:
    return float((np.arange(len(pmf)) * np.asarray(pmf)).sum())


@pytest.mark.parametrize("fn", DIST_FNS)
def test_every_distribution_is_a_valid_pmf_flat_over_the_horizon(fn):
    out = fn(INTERMITTENT, 5)
    assert len(out) == 5
    for pmf in out:
        assert np.all(np.asarray(pmf) >= 0.0)
        assert float(np.sum(pmf)) == pytest.approx(1.0, abs=1e-12)
    # These methods estimate a RATE, so the distribution is the same every step.
    assert all(np.array_equal(out[0], p) for p in out[1:])


@pytest.mark.parametrize(
    "dist_fn,point_fn",
    [(croston_dist, croston), (sba_dist, sba), (tsb_dist, tsb)],
)
def test_distribution_mean_equals_the_point_forecast(dist_fn, point_fn):
    """The by-construction property: E[Y] = p * z is exactly the flat rate.

    If this ever breaks, the point and distributional leaderboards are scoring two
    different models under one name.
    """
    for series in (INTERMITTENT, [0, 0, 0, 4, 0, 9, 0, 0, 2], [5, 5, 5, 5, 5, 5]):
        assert _mean(dist_fn(series, 1)[0]) == pytest.approx(point_fn(series, 1)[0], rel=1e-6)


def test_compound_bernoulli_zero_probability_is_one_minus_p():
    """Croston's occurrence probability is 1 / smoothed-interval, by the memoryless
    assumption documented in the module. P(Y=0) must equal 1 - that."""
    y = np.asarray(INTERMITTENT, dtype=float)
    nz = np.flatnonzero(y > 0)
    intervals = np.diff(np.concatenate([[-1], nz])).astype(float)
    level = intervals[0]
    for v in intervals[1:]:
        level = ALPHA * v + (1 - ALPHA) * level
    assert croston_dist(INTERMITTENT, 1)[0][0] == pytest.approx(1.0 - 1.0 / level)


def test_sba_shifts_probability_not_size():
    """SBA applies (1 - alpha/2) to the OCCURRENCE PROBABILITY, so its P(Y=0) is
    strictly larger than Croston's while the conditional size law is identical."""
    c = croston_dist(INTERMITTENT, 1, alpha=ALPHA)[0]
    s = sba_dist(INTERMITTENT, 1, alpha=ALPHA)[0]
    p_c, p_s = 1.0 - c[0], 1.0 - s[0]
    assert p_s == pytest.approx(p_c * (1 - ALPHA / 2))
    # Conditional size law (renormalised over k >= 1) is untouched by the correction.
    np.testing.assert_allclose(c[1:] / c[1:].sum(), s[1:] / s[1:].sum(), rtol=1e-10)


def test_tsb_distribution_uses_its_own_probability():
    """TSB is native: P(Y=0) is 1 - its smoothed occurrence probability."""
    active_then_dead = [3, 2, 4, 3] + [0] * 20
    dead = tsb_dist(active_then_dead, 1)[0][0]
    alive = tsb_dist([3, 2, 4, 3], 1)[0][0]
    assert dead > alive          # obsolescence pushes mass onto zero


@pytest.mark.parametrize("fn", DIST_FNS)
def test_all_zero_series_gives_a_point_mass_at_zero(fn):
    pmf = fn([0.0] * 20, 1)[0]
    assert pmf[0] == pytest.approx(1.0)


def test_naive_and_zero_are_degenerate():
    assert np.array_equal(naive_last_dist([1, 2, 5], 1)[0], point_mass(5))
    assert np.array_equal(zero_dist([1, 2, 5], 1)[0], point_mass(0))


def test_climatology_reproduces_the_empirical_frequencies():
    series = [0, 0, 0, 1, 1, 2]
    pmf = climatology_dist(series, 1)[0]
    np.testing.assert_allclose(pmf, [3 / 6, 2 / 6, 1 / 6])
    assert _mean(pmf) == pytest.approx(float(np.mean(series)))


def test_overdispersed_sizes_widen_the_size_law():
    """When non-zero sizes are overdispersed the size law leaves the Poisson limit,
    putting more mass in the upper tail at the SAME mean."""
    tight = [0, 3, 0, 3, 0, 3, 0, 3, 0, 3, 0, 3]
    spread = [0, 1, 0, 1, 0, 10, 0, 1, 0, 1, 0, 10]
    p_tight = croston_dist(tight, 1)[0]
    p_spread = croston_dist(spread, 1)[0]
    assert float(p_spread[8:].sum()) > float(p_tight[8:].sum())


# ── Scaled distributional errors ─────────────────────────────────────────────

def test_scaled_crps_of_a_degenerate_distribution_equals_mase():
    """The identity that makes the two leaderboards comparable, end to end."""
    train = INTERMITTENT
    actuals = [0.0, 2.0, 1.0, 0.0]
    dists = naive_last_dist(train, len(actuals))
    point = naive_last(train, len(actuals))
    assert scaled_crps(train, actuals, dists) == pytest.approx(mase(train, actuals, point))


def test_scaled_scores_share_the_training_only_mase_denominator():
    """No leakage: the denominator must be a function of the TRAINING window alone,
    so changing the held-out actuals must not change it."""
    train = INTERMITTENT
    assert mase_denominator(train) == mase_denominator(train)
    d1 = scaled_crps(train, [0.0], zero_dist(train, 1))
    d2 = scaled_crps(train, [7.0], zero_dist(train, 1))
    denom = mase_denominator(train)
    assert d1 == pytest.approx(0.0 / denom)
    assert d2 == pytest.approx(7.0 / denom)


def test_scaled_scores_are_nan_when_the_denominator_is_undefined():
    flat = [5.0] * 6
    assert math.isnan(mase_denominator(flat))
    assert math.isnan(scaled_crps(flat, [5.0], naive_last_dist(flat, 1)))
    assert math.isnan(scaled_pinball(flat, [5.0], naive_last_dist(flat, 1)))


def test_scaled_scores_reject_a_length_mismatch():
    with pytest.raises(ValueError):
        scaled_crps(INTERMITTENT, [1.0, 2.0], naive_last_dist(INTERMITTENT, 3))
    with pytest.raises(ValueError):
        scaled_pinball(INTERMITTENT, [1.0, 2.0], naive_last_dist(INTERMITTENT, 3))


def test_a_hedged_distribution_beats_a_degenerate_one_on_crps():
    """The motivating result in miniature: on an intermittent series the degenerate
    zero forecast can win MASE while losing to a real distribution on CRPS."""
    train = [0, 0, 2, 0, 0, 0, 1, 0, 0, 3, 0, 0, 0, 1, 0, 0] * 2
    actuals = [0.0, 0.0, 3.0, 0.0, 1.0, 0.0]
    zero_mase = mase(train, actuals, [0.0] * len(actuals))
    tsb_mase = mase(train, actuals, tsb(train, len(actuals)))
    zero_crps = scaled_crps(train, actuals, zero_dist(train, len(actuals)))
    tsb_crps = scaled_crps(train, actuals, tsb_dist(train, len(actuals)))
    assert zero_mase < tsb_mase        # the degenerate forecast wins on MASE
    assert tsb_crps < zero_crps        # and loses under a proper scoring rule
