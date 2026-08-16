"""Unit tests for the MCB / Diebold-Mariano / Clark-West machinery.

These are statistical tests, so the tests-of-the-tests check them against three
independent things: scipy's own Friedman implementation, the published Nemenyi
critical-value table (Demsar 2006, Table 5), and constructed data whose answer is
known by design — including the nested case where Clark-West must succeed and
Diebold-Mariano must fail, since using DM there is the specific error the module
exists to avoid.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from app.ml.model_comparison import (
    clark_west,
    diebold_mariano,
    mcb_test,
    nemenyi_critical_difference,
)

#: Demsar (2006), JMLR 7:1-30, Table 5 — critical values q_alpha for the two-tailed
#: Nemenyi test at alpha = 0.05, indexed by number of methods.
DEMSAR_Q05 = {2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949, 8: 3.031,
              9: 3.102, 10: 3.164}
#: The published table is given to three decimals and is itself slightly imprecise —
#: e.g. the exact studentised-range value for k=3 is 2.34370, which rounds to 2.344,
#: not the tabulated 2.343. A 2e-3 tolerance accepts the table's own rounding error
#: while still catching any real mistake in the formula (a wrong sqrt(2) factor or a
#: one-tailed quantile would be off by tenths, not thousandths).
DEMSAR_TABLE_TOLERANCE = 2e-3


# ── Friedman + Nemenyi ────────────────────────────────────────────────────────

def test_friedman_statistic_matches_scipy():
    rng = np.random.default_rng(11)
    losses = rng.gamma(2.0, 1.0, size=(300, 5)) + np.array([0.0, 0.1, 0.2, 0.3, 0.4])
    res = mcb_test(losses, list("abcde"))
    expected = stats.friedmanchisquare(*[losses[:, j] for j in range(5)])
    assert res.friedman_chi2 == pytest.approx(float(expected.statistic), rel=1e-9)
    assert res.friedman_p == pytest.approx(float(expected.pvalue), rel=1e-9)


@pytest.mark.parametrize("k", sorted(DEMSAR_Q05))
def test_nemenyi_critical_difference_matches_the_published_table(k):
    """CD = q_alpha * sqrt(k(k+1)/(6N)); recover q_alpha and compare to Demsar."""
    n = 100
    cd = nemenyi_critical_difference(k, n, alpha=0.05)
    q = cd / np.sqrt(k * (k + 1) / (6.0 * n))
    assert q == pytest.approx(DEMSAR_Q05[k], abs=DEMSAR_TABLE_TOLERANCE)


def test_critical_difference_shrinks_with_more_series():
    """More replications must make the test more able to separate methods."""
    assert nemenyi_critical_difference(5, 2658) < nemenyi_critical_difference(5, 100)


def test_mean_ranks_order_matches_the_designed_ordering():
    rng = np.random.default_rng(3)
    base = rng.gamma(2.0, 1.0, size=(400, 1))
    losses = base * np.array([1.0, 1.2, 1.4]) + rng.normal(0, 0.01, size=(400, 3))
    res = mcb_test(losses, ["best", "mid", "worst"])
    assert res.mean_ranks["best"] < res.mean_ranks["mid"] < res.mean_ranks["worst"]
    assert res.friedman_p < 1e-6


def test_identical_methods_are_not_separated_and_form_one_clique():
    """Three copies of the same forecaster must land in a single clique — the CD
    diagram's way of saying 'the data cannot tell these apart'."""
    rng = np.random.default_rng(5)
    col = rng.gamma(2.0, 1.0, size=(200, 1))
    losses = np.hstack([col, col.copy(), col.copy()])
    res = mcb_test(losses, ["a", "b", "c"])
    assert res.friedman_p > 0.05
    assert res.cliques == [["a", "b", "c"]]
    assert all(not p["significant"] for p in res.pairwise)


def test_cliques_group_only_the_methods_within_a_critical_difference():
    """Two indistinguishable pairs, well separated from each other, must give
    exactly two cliques — not one (over-merging) and not none (over-splitting).

    a/b are drawn from an identical law, as are c/d, so within a pair the rank is a
    coin flip and the mean ranks coincide; between pairs the 1.6x loss gap is far
    larger than the critical difference.
    """
    rng = np.random.default_rng(9)
    n = 3000
    base = rng.gamma(2.0, 1.0, size=(n, 1))
    noise = rng.normal(0, 0.35, size=(n, 4))
    losses = base * np.array([1.0, 1.0, 1.6, 1.6]) + noise
    res = mcb_test(losses, ["a", "b", "c", "d"])
    assert sorted(sorted(c) for c in res.cliques) == [["a", "b"], ["c", "d"]]


def test_mcb_rejects_an_unbalanced_panel():
    """A NaN would silently make the mean ranks incomparable across methods."""
    losses = np.array([[1.0, 2.0], [np.nan, 1.0], [2.0, 1.0]])
    with pytest.raises(ValueError):
        mcb_test(losses, ["a", "b"])


def test_mcb_validates_its_shape_arguments():
    with pytest.raises(ValueError):
        mcb_test(np.ones((5, 2)), ["only_one"])
    with pytest.raises(ValueError):
        mcb_test(np.ones(5), ["a"])
    with pytest.raises(ValueError):
        mcb_test(np.ones((5, 1)), ["a"])


# ── Diebold-Mariano ───────────────────────────────────────────────────────────

def test_dm_sign_convention_positive_means_the_candidate_wins():
    rng = np.random.default_rng(13)
    baseline = rng.gamma(3.0, 1.0, size=500)
    candidate = baseline * 0.6
    res = diebold_mariano(baseline, candidate, "baseline", "candidate")
    assert res.mean_loss_difference > 0
    assert res.statistic > 0
    assert res.p_value < 1e-10


def test_dm_is_antisymmetric():
    rng = np.random.default_rng(17)
    a, b = rng.gamma(2.0, 1.0, size=400), rng.gamma(2.0, 1.1, size=400)
    fwd = diebold_mariano(a, b)
    rev = diebold_mariano(b, a)
    assert fwd.statistic == pytest.approx(-rev.statistic)
    assert fwd.p_value == pytest.approx(rev.p_value)


def test_dm_does_not_reject_for_equally_good_methods():
    rng = np.random.default_rng(19)
    a, b = rng.gamma(2.0, 1.0, size=1000), rng.gamma(2.0, 1.0, size=1000)
    assert diebold_mariano(a, b).p_value > 0.05


def test_dm_handles_identical_losses_without_dividing_by_zero():
    a = np.arange(10.0)
    res = diebold_mariano(a, a.copy())
    assert res.statistic == 0.0
    assert res.p_value == 1.0


def test_dm_validates_inputs():
    with pytest.raises(ValueError):
        diebold_mariano([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        diebold_mariano([1.0, 2.0], [1.0, 2.0])


# ── Clark-West, and why it is not Diebold-Mariano ─────────────────────────────

def _nested_panel(seed: int, signal: float, n_series: int = 400, per_series: int = 12):
    """A panel where the unrestricted model sees a real signal the restricted one
    cannot, plus estimation noise that penalises it under plain MSPE."""
    rng = np.random.default_rng(seed)
    n = n_series * per_series
    x = rng.normal(size=n)
    y = signal * x + rng.normal(scale=1.0, size=n)
    restricted = np.zeros(n)                                   # the nested model
    unrestricted = signal * x + rng.normal(scale=0.45, size=n)  # + estimation noise
    idx = np.repeat(np.arange(n_series), per_series)
    return y, restricted, unrestricted, idx


def test_dm_and_clark_west_disagree_on_a_nested_pair_and_clark_west_is_right():
    """The reason this module carries two tests instead of one.

    Construction: y = 0.3x + e with e ~ N(0,1). The restricted model predicts 0
    (MSPE = 0.3^2 + 1 = 1.09). The unrestricted model knows x but carries
    estimation noise of sd 0.45 (MSPE = 1 + 0.45^2 = 1.2025). So the larger model
    is genuinely worse OUT OF SAMPLE while the extra predictor genuinely has
    population predictive content.

    DM therefore reports the unrestricted model as significantly WORSE — the
    correct answer to "which fitted model was more accurate", and the wrong answer
    to "does the extra term belong in the model". Clark-West asks the second
    question, adds the estimation-noise term back, and correctly rejects the null
    that the restricted model is the data-generating process. Running DM here and
    concluding the predictor is useless is exactly the error being guarded against.
    """
    y, restricted, unrestricted, idx = _nested_panel(seed=23, signal=0.30)

    cw = clark_west(y, restricted, unrestricted, series_index=idx)
    assert cw.statistic > 0
    assert cw.p_value < 0.01

    # Plain DM on the same data, per-series mean squared error.
    n_series = int(idx.max()) + 1
    mse_r = np.array([np.mean((y[idx == i] - restricted[idx == i]) ** 2) for i in range(n_series)])
    mse_u = np.array([np.mean((y[idx == i] - unrestricted[idx == i]) ** 2) for i in range(n_series)])
    dm = diebold_mariano(mse_r, mse_u, "restricted", "unrestricted")
    assert dm.mean_loss_difference < 0      # DM: the larger model has HIGHER MSPE
    assert dm.p_value < 0.01                # and DM calls that difference significant
    assert cw.statistic > 0 > dm.statistic  # the two tests point in opposite directions


def test_clark_west_does_not_reject_when_the_extra_parameters_are_pure_noise():
    """Correct null behaviour: if the restricted model is true, adding noise-only
    parameters must not produce a significant Clark-West statistic."""
    rng = np.random.default_rng(29)
    n_series, per_series = 500, 10
    n = n_series * per_series
    y = rng.normal(size=n)
    restricted = np.zeros(n)
    unrestricted = rng.normal(scale=0.3, size=n)     # noise, uncorrelated with y
    idx = np.repeat(np.arange(n_series), per_series)
    res = clark_west(y, restricted, unrestricted, series_index=idx)
    assert res.p_value > 0.05


def test_clark_west_is_one_sided():
    """A worse unrestricted model must give a large p-value, not a small one."""
    y, restricted, _, idx = _nested_panel(seed=31, signal=0.0)
    rng = np.random.default_rng(37)
    harmful = rng.normal(scale=3.0, size=len(y)) - y   # anti-correlated with y
    res = clark_west(y, restricted, harmful, series_index=idx)
    assert res.p_value > 0.5


def test_clark_west_averages_within_series_before_the_cross_sectional_test():
    """The panel convention: the series is the replication unit, so collapsing 12
    observations per series must change n from 4800 to 400."""
    y, restricted, unrestricted, idx = _nested_panel(seed=41, signal=0.3)
    grouped = clark_west(y, restricted, unrestricted, series_index=idx)
    pooled = clark_west(y, restricted, unrestricted)
    assert grouped.n == 400
    assert pooled.n == len(y)


def test_clark_west_validates_inputs():
    with pytest.raises(ValueError):
        clark_west([1.0, 2.0], [0.0, 0.0], [0.0])
    with pytest.raises(ValueError):
        clark_west([1.0, 2.0, 3.0], [0.0] * 3, [0.0] * 3, series_index=[0, 1])
    with pytest.raises(ValueError):
        clark_west([1.0, 2.0], [0.0, 0.0], [0.0, 0.0])
