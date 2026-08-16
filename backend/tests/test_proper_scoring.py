"""Unit tests for the proper scoring rules on discrete predictive distributions.

These pin the properties that make the distributional leaderboard mean anything:
CRPS is computed by the exact threshold decomposition (not a Gaussian shortcut),
it collapses to absolute error on a point forecast, it is actually *proper*, and
the pinball loss is minimised by the quantile it claims to score.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ml.proper_scoring import (
    crps_discrete,
    mean_pinball_loss,
    pinball_loss,
    quantile_from_pmf,
)


def _pmf(*mass: float) -> np.ndarray:
    arr = np.asarray(mass, dtype=float)
    return arr / arr.sum()


def _degenerate(k: int, length: int = 1) -> np.ndarray:
    pmf = np.zeros(max(k + 1, length))
    pmf[k] = 1.0
    return pmf


# ── CRPS: the identity that ties the two leaderboards together ────────────────

@pytest.mark.parametrize("f,y", [(0, 0), (0, 3), (5, 2), (2, 5), (7, 7), (1, 40)])
def test_crps_of_a_point_forecast_is_absolute_error(f, y):
    """CRPS(degenerate at f, y) == |f - y| exactly.

    This is why a point method and a distributional method can share one axis:
    scoring a point forecast as a zero-spread distribution reproduces MAE, so
    scaled CRPS reproduces MASE.
    """
    assert crps_discrete(_degenerate(f), y) == pytest.approx(abs(f - y))


def test_crps_scores_observations_outside_the_support():
    """An actual beyond the pmf's last bin must still be scored, not silently clipped."""
    pmf = _pmf(0.5, 0.3, 0.2)          # support 0..2
    # Beyond the support F(k) == 1, so each extra threshold contributes (1-0)^2 = 1.
    near = crps_discrete(pmf, 2.0)
    far = crps_discrete(pmf, 5.0)
    assert far == pytest.approx(near + 3.0)


def test_crps_is_zero_only_for_a_perfect_point_forecast():
    assert crps_discrete(_degenerate(4), 4) == pytest.approx(0.0)
    assert crps_discrete(_pmf(0.5, 0.5), 0) > 0.0


def test_crps_is_proper_the_true_distribution_wins():
    """A strictly proper rule is minimised in expectation by the truth.

    Draw from P, score under P and under a wrong Q; P must win. This is the
    property MASE does NOT have, and the reason the whole exercise exists.
    """
    rng = np.random.default_rng(0)
    p = _pmf(0.70, 0.15, 0.10, 0.05)
    q = _pmf(0.25, 0.25, 0.25, 0.25)
    draws = rng.choice(len(p), size=40_000, p=p)
    score_p = float(np.mean([crps_discrete(p, y) for y in draws]))
    score_q = float(np.mean([crps_discrete(q, y) for y in draws]))
    assert score_p < score_q


def test_crps_is_not_the_gaussian_closed_form():
    """Guard against someone 'simplifying' to the Gaussian formula.

    For a distribution with an atom at zero the Gaussian closed form
    sigma*(z*(2*Phi(z)-1) + 2*phi(z) - 1/sqrt(pi)) is simply a different number.
    The point of the discrete form is that it makes no continuity assumption.
    """
    from math import erf, exp, pi, sqrt

    pmf = _pmf(0.76, 0.14, 0.07, 0.03)   # ~the panel's zero-inflation
    y = 2.0
    ks = np.arange(len(pmf), dtype=float)
    mu = float((ks * pmf).sum())
    sigma = float(np.sqrt(((ks - mu) ** 2 * pmf).sum()))
    z = (y - mu) / sigma
    gaussian = sigma * (z * (erf(z / sqrt(2))) + 2 * exp(-z * z / 2) / sqrt(2 * pi) - 1 / sqrt(pi))
    assert crps_discrete(pmf, y) != pytest.approx(gaussian, rel=0.05)


def test_crps_rejects_a_degenerate_pmf():
    with pytest.raises(ValueError):
        crps_discrete([0.0, 0.0], 1.0)
    with pytest.raises(ValueError):
        crps_discrete([-0.5, 1.5], 1.0)
    with pytest.raises(ValueError):
        crps_discrete([], 1.0)


# ── Quantiles and pinball loss ────────────────────────────────────────────────

def test_quantile_is_the_generalised_inverse_cdf():
    pmf = _pmf(0.5, 0.2, 0.3)            # F = 0.5, 0.7, 1.0
    assert quantile_from_pmf(pmf, 0.4) == 0.0
    assert quantile_from_pmf(pmf, 0.5) == 0.0
    assert quantile_from_pmf(pmf, 0.6) == 1.0
    assert quantile_from_pmf(pmf, 0.95) == 2.0


def test_pinball_loss_is_minimised_by_the_tau_quantile():
    """The defining property, checked by brute force against every other candidate."""
    rng = np.random.default_rng(7)
    pmf = _pmf(0.6, 0.2, 0.12, 0.08)
    draws = rng.choice(len(pmf), size=30_000, p=pmf)
    for tau in (0.1, 0.5, 0.9):
        best_q = quantile_from_pmf(pmf, tau)
        expected = {
            q: float(np.mean([pinball_loss(q, y, tau) for y in draws]))
            for q in range(len(pmf))
        }
        assert min(expected, key=lambda q: expected[q]) == best_q


def test_pinball_is_asymmetric_in_the_direction_tau_implies():
    """High tau must punish UNDER-forecasting harder — that asymmetry is the whole
    reason a service level maps onto a quantile."""
    assert pinball_loss(q=5, y=10, tau=0.9) > pinball_loss(q=10, y=5, tau=0.9)
    assert pinball_loss(q=5, y=10, tau=0.1) < pinball_loss(q=10, y=5, tau=0.1)
    assert pinball_loss(q=5, y=10, tau=0.5) == pytest.approx(pinball_loss(q=10, y=5, tau=0.5))


def test_mean_pinball_over_a_fine_grid_approaches_half_the_crps():
    """int_0^1 L_tau dtau == CRPS / 2 — the identity linking the two scores."""
    pmf = _pmf(0.5, 0.2, 0.15, 0.1, 0.05)
    grid = [(i + 0.5) / 400 for i in range(400)]
    for y in (0, 1, 3, 6):
        assert mean_pinball_loss(pmf, y, grid) == pytest.approx(
            crps_discrete(pmf, y) / 2.0, rel=0.01
        )


def test_pinball_rejects_levels_outside_the_open_unit_interval():
    for bad in (0.0, 1.0, -0.1, 1.2):
        with pytest.raises(ValueError):
            pinball_loss(1.0, 2.0, bad)
        with pytest.raises(ValueError):
            quantile_from_pmf(_pmf(1.0, 1.0), bad)
    with pytest.raises(ValueError):
        mean_pinball_loss(_pmf(1.0, 1.0), 1.0, [])
