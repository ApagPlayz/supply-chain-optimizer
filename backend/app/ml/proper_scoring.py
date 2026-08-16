"""Proper scoring rules for *discrete* (count) predictive distributions.

Point-forecast metrics answer "how far off was the number?". Proper scoring rules
answer "how good was the whole distribution?" — and they matter here for a specific,
measurable reason:

    MAE (and therefore MASE) is minimised by the conditional MEDIAN. On intermittent
    demand the conditional median is frequently ZERO — the Monash car-parts panel is
    24.1% non-zero — so a MASE leaderboard can be topped by a forecast that is
    degenerate at (or near) zero. It is not wrong, it is answering a question nobody
    asked: the planner needs P(demand > stock), not the median.

A scoring rule S is *proper* if the forecaster minimises their expected score by
reporting their true belief, and *strictly* proper if that optimum is unique
(Gneiting & Raftery 2007, JASA 102(477):359-378). CRPS and the pinball (check) loss
are both strictly proper; MASE/RMSSE are not proper scoring rules at all, because
they only see a point.

This module is numpy-only and knows nothing about demand — it takes a pmf over the
non-negative integers and an observation. `app/ml/intermittent.py` provides the
scaled (per-series-comparable) wrappers that share MASE's training-only denominator.

Implementations
---------------
crps_discrete
    The threshold-decomposition (Ranked Probability Score) form

        CRPS(F, y) = SUM_{k=0..inf} ( F(k) - 1{y <= k} )^2

    which is the *exact* CRPS for an integer-valued outcome, not an approximation.
    The Gaussian closed form is deliberately NOT used: it assumes a continuous,
    symmetric, unbounded predictive law, and count demand with an atom of ~76% at
    zero violates every part of that.

    Useful identity, asserted in the tests: for a distribution degenerate at f,
    CRPS(F, y) = |f - y|. So CRPS reduces to absolute error exactly when the
    "distribution" is a point forecast — which is what makes a point method and a
    distributional method directly comparable on one axis.

pinball_loss
    L_tau(q, y) = tau * (y - q)      if y >= q
                  (1 - tau) * (q - y) if y <  q
    Minimised in expectation by the tau-quantile. This is the same loss the
    newsvendor pays with tau = Cu / (Cu + Co), which is why step 1.4 of the build
    plan can reuse it directly as a decision cost.

mean_pinball_loss
    Averaged over a grid of quantile levels — the M5 "Uncertainty" track metric
    (before scaling). Note that the average of the pinball loss over tau ~ U(0,1)
    equals CRPS / 2, so the two agree in the limit of a fine grid; both are reported
    because the per-tau breakdown is what a service-level conversation needs.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

__all__ = [
    "DEFAULT_QUANTILE_LEVELS",
    "crps_discrete",
    "mean_pinball_loss",
    "pinball_loss",
    "quantile_from_pmf",
]

# M5-Uncertainty-style grid, plus the deciles a service-level target lands on.
DEFAULT_QUANTILE_LEVELS: tuple[float, ...] = (
    0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99,
)


def _as_cdf(pmf: Sequence[float]) -> np.ndarray:
    """Normalise a pmf over 0..K and return its cdf (last entry forced to 1.0)."""
    p = np.asarray(pmf, dtype=float)
    if p.ndim != 1 or p.size == 0:
        raise ValueError("pmf must be a non-empty 1-D array over counts 0..K")
    if np.any(p < -1e-12):
        raise ValueError("pmf has negative mass")
    total = float(p.sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("pmf does not sum to a positive finite number")
    cdf = np.cumsum(p / total)
    cdf[-1] = 1.0
    return cdf


def crps_discrete(pmf: Sequence[float], y: float) -> float:
    """Exact CRPS for an integer-supported predictive distribution.

    Args:
        pmf: probability mass on counts 0, 1, ..., K (need not be normalised).
        y:   the realised count.

    Returns:
        SUM_k (F(k) - 1{y <= k})^2, summed far enough to cover `y` even when it
        falls outside the pmf's support (beyond the support F(k) == 1, so the
        remaining terms are (1 - 1{y <= k})^2 and are picked up correctly).

    Lower is better; 0 iff the distribution is degenerate at y.
    """
    cdf = _as_cdf(pmf)
    y = float(y)
    k_needed = int(np.ceil(y)) if np.isfinite(y) else 0
    k_max = max(cdf.size - 1, k_needed)
    if k_max >= cdf.size:
        cdf = np.concatenate([cdf, np.ones(k_max - cdf.size + 1)])
    ks = np.arange(k_max + 1, dtype=float)
    indicator = (ks >= y).astype(float)  # 1{y <= k}
    return float(np.sum((cdf - indicator) ** 2))


def quantile_from_pmf(pmf: Sequence[float], tau: float) -> float:
    """Smallest count k with F(k) >= tau — the standard discrete quantile.

    This is the generalised inverse cdf, so it is the value that minimises expected
    pinball loss at level `tau` under the given pmf.
    """
    if not 0.0 < tau < 1.0:
        raise ValueError("tau must lie strictly between 0 and 1")
    cdf = _as_cdf(pmf)
    idx = int(np.searchsorted(cdf, tau, side="left"))
    return float(min(idx, cdf.size - 1))


def pinball_loss(q: float, y: float, tau: float) -> float:
    """Check/pinball loss at quantile level `tau`. Minimised by the tau-quantile."""
    if not 0.0 < tau < 1.0:
        raise ValueError("tau must lie strictly between 0 and 1")
    diff = float(y) - float(q)
    return float(tau * diff) if diff >= 0 else float((tau - 1.0) * diff)


def mean_pinball_loss(
    pmf: Sequence[float],
    y: float,
    levels: Sequence[float] = DEFAULT_QUANTILE_LEVELS,
) -> float:
    """Average pinball loss of a pmf's quantiles over a grid of levels.

    The M5 Uncertainty track's per-observation loss (before the series-level
    scaling). Strictly proper as a set, since each term is strictly proper at its
    own level.
    """
    if len(levels) == 0:
        raise ValueError("levels must be non-empty")
    cdf = _as_cdf(pmf)
    total = 0.0
    for tau in levels:
        if not 0.0 < tau < 1.0:
            raise ValueError("every level must lie strictly between 0 and 1")
        idx = int(np.searchsorted(cdf, tau, side="left"))
        q = float(min(idx, cdf.size - 1))
        total += pinball_loss(q, y, tau)
    return total / float(len(levels))
