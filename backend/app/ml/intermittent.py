"""Intermittent-demand forecasting methods + scaled-error metrics.

Component/spare-part demand is *intermittent*: long runs of zero interrupted by
small, sporadic orders. Ordinary exponential smoothing / Prophet are known to be
biased on this pattern, so real component planners use Croston-family estimators.
This module implements the three that matter, plus the scaled-error metrics
(MASE, RMSSE) the M-competitions and Monash benchmarks report and their
distributional counterparts — none of which require a heavy dependency (numpy
only, same as forecast_metrics.py).

Estimators (each returns a *flat* per-period rate forecast — the standard output
of these methods, which estimate a demand RATE, not a shape):

  croston  — split the series into non-zero demand SIZES and the INTERVALS between
             them; smooth each with SES(alpha); forecast = size_hat / interval_hat.
  sba      — Syntetos-Boylan Approximation: Croston is biased high; multiply by
             (1 - alpha/2). The de-facto default in industry demand planning.
  tsb      — Teunter-Syntetos-Babai: updates a demand PROBABILITY every period
             (not just at non-zero points), so it decays obsolete SKUs correctly.

Scaled errors (need the training series to form the denominator, so they live here
rather than in forecast_metrics.py):

  mase     — MAE / MAE of the in-sample seasonal-naive one-step forecast.
  rmsse    — sqrt(MSE / MSE of the in-sample naive one-step forecast)  (M5 metric).

Both are scale-free and comparable across SKUs; < 1.0 means "beats naive".
Series whose in-sample naive denominator is 0 (e.g. an all-constant train window)
are undefined and must be skipped by the caller.


PREDICTIVE DISTRIBUTIONS
========================
A point rate forecast cannot answer the question a planner actually asks — "how
much do I stock so I am short less than 5% of the time?" — so every method above
also has a `*_dist` twin returning a **discrete predictive distribution** over
counts 0, 1, 2, ..., scored by CRPS / pinball loss in `app/ml/proper_scoring.py`.

All of them share one parameterisation, the **compound Bernoulli** model that is
the standard structural description of intermittent demand:

    Y = B * S,   B ~ Bernoulli(p),   S ~ ZeroTruncatedNegBin(mean z, shape r)

i.e. in any period demand occurs with probability p, and *given* an occurrence the
order size is a strictly positive count with mean z. Then E[Y] = p * z, which is
exactly the flat rate each point method already emits — so **every distribution
below has the same mean as its point twin, by construction** (pinned in the
tests). The methods differ only in how they estimate (p, z):

  tsb_dist         p = TSB's smoothed occurrence probability, z = TSB's smoothed
                   size. ASSUMPTION: none beyond the compound-Bernoulli structure.
                   TSB is already parameterised this way — this is the method the
                   distributional form is native to.

  croston_dist     Croston smooths the SIZE (z_hat) and the INTER-ARRIVAL INTERVAL
                   (p_hat), and gives no probability. ASSUMPTION: the occurrence
                   process is memoryless, i.e. arrivals are i.i.d. Bernoulli(p), in
                   which case inter-arrival times are Geometric(p) with mean 1/p,
                   so  p = 1 / p_hat.  This is the renewal process Croston's own
                   derivation assumes (Croston 1972 posits Bernoulli arrivals), so
                   the assumption is not an addition to the method — it is a
                   restatement of the model Croston was derived under. Because
                   intervals are >= 1 by construction, p <= 1 always.

  sba_dist         Same as Croston, with the Syntetos-Boylan correction. ASSUMPTION:
                   the (1 - alpha/2) factor is applied to the OCCURRENCE
                   PROBABILITY, not the size. Justified: Syntetos & Boylan (2001)
                   show Croston's bias comes from E[1/p_hat] != 1/E[p_hat] — a
                   Jensen gap in the *inverse-interval* term. The size estimator is
                   unbiased. So p = (1 - alpha/2) / p_hat, z unchanged. This both
                   places the correction where the bias is and reproduces the SBA
                   point forecast exactly.

  naive_last_dist  ASSUMPTION: none — this is the point forecast lifted to a
                   distribution *degenerate* at the last observed value (all mass
                   on one count, zero spread). Deliberately unhedged: it is the
                   honest probabilistic reading of "repeat the last number", and it
                   makes CRPS collapse to absolute error, so the point and
                   distributional leaderboards share a common anchor.

  zero_dist        Degenerate at 0. Not a straw man: MAE/MASE is minimised by the
                   conditional MEDIAN, and on a 24%-non-zero panel that median is
                   usually 0 — so this is the degenerate forecast a MASE
                   leaderboard is at risk of rewarding, included precisely so the
                   risk can be MEASURED rather than asserted.

  climatology_dist The in-sample EMPIRICAL distribution of the training window
                   (relative frequency of each observed count). ASSUMPTION:
                   exchangeability of the training window with the test window —
                   no trend, no obsolescence. The standard probabilistic reference
                   forecast, and the only non-degenerate baseline here.

Size distribution. `S` is zero-truncated negative binomial, with the Poisson limit
(shape -> infinity) used whenever the in-sample non-zero sizes are not overdispersed
(sample variance <= sample mean). That default is the common case, not a shortcut:
on the Monash car-parts panel the non-zero sizes have a median variance/mean ratio
of 0.42 across series and only 17.6% of series exceed 1.0 — and a zero-truncated
Poisson with lambda ~ 1 implies a ratio of 0.418, so the panel's order sizes are
essentially ZTP. The shape, when needed, is the method-of-moments plug-in
r = m^2 / (v - m) computed on the truncated (non-zero) sample; applying the
untruncated moment relation to a truncated sample is an APPROXIMATION and is
flagged as such here rather than solved jointly, because it only binds on the ~18%
overdispersed minority and the CRPS difference is third-order.
"""
from __future__ import annotations

import math
from typing import List, Sequence

import numpy as np

from app.ml.proper_scoring import DEFAULT_QUANTILE_LEVELS, crps_discrete, mean_pinball_loss

__all__ = [
    "croston",
    "sba",
    "tsb",
    "naive_last",
    "mase",
    "rmsse",
    "croston_dist",
    "sba_dist",
    "tsb_dist",
    "naive_last_dist",
    "zero_dist",
    "climatology_dist",
    "point_mass",
    "mase_denominator",
    "scaled_crps",
    "scaled_pinball",
]


def _ses_recursion(values: np.ndarray, alpha: float) -> float:
    """Return the final level of a simple-exponential-smoothing pass."""
    level = float(values[0])
    for v in values[1:]:
        level = alpha * float(v) + (1.0 - alpha) * level
    return level


def _croston_components(train: Sequence[float], alpha: float) -> tuple[float, float] | None:
    """Return Croston's (smoothed size, smoothed inter-arrival interval), or None.

    None means the series has no non-zero demand at all, so there is nothing to
    decompose. Split out from `croston` so the point forecast and the predictive
    distribution are guaranteed to be built from the SAME two estimates.
    """
    y = np.asarray(train, dtype=float)
    nz_idx = np.flatnonzero(y > 0)
    if nz_idx.size == 0:
        return None
    if nz_idx.size == 1:
        # One observation: the interval is the whole window, size is that observation.
        return float(y[nz_idx[0]]), float(len(y))

    sizes = y[nz_idx]
    intervals = np.diff(np.concatenate([[-1], nz_idx])).astype(float)  # gap incl. first
    z_hat = _ses_recursion(sizes, alpha)         # smoothed demand size
    p_hat = _ses_recursion(intervals, alpha)     # smoothed inter-arrival interval
    return float(z_hat), float(p_hat if p_hat > 0 else 1.0)


def croston(train: Sequence[float], horizon: int, alpha: float = 0.1) -> List[float]:
    """Croston's method — flat rate forecast repeated over the horizon.

    Returns a zero forecast when there are no non-zero demands (nothing to
    decompose) so the forecast is always defined.
    """
    parts = _croston_components(train, alpha)
    if parts is None:
        return [0.0] * horizon
    z_hat, p_hat = parts
    return [float(z_hat / p_hat)] * horizon


def sba(train: Sequence[float], horizon: int, alpha: float = 0.1) -> List[float]:
    """Syntetos-Boylan Approximation — bias-corrected Croston."""
    base = croston(train, horizon, alpha)[0]
    return [float(base * (1.0 - alpha / 2.0))] * horizon


def _tsb_components(train: Sequence[float], alpha: float, beta: float) -> tuple[float, float]:
    """Return TSB's (occurrence probability p, conditional size z).

    These are exactly the two parameters of the compound-Bernoulli predictive
    distribution, which is why TSB is the method the distributional form is native
    to. Split out so `tsb` and `tsb_dist` cannot drift apart.
    """
    y = np.asarray(train, dtype=float)
    if y.size == 0:
        return 0.0, 0.0
    nz = y > 0
    p = float(nz.mean()) if nz.any() else 0.0            # demand probability
    z = float(y[nz].mean()) if nz.any() else 0.0         # demand size
    for t in range(len(y)):
        occurred = 1.0 if y[t] > 0 else 0.0
        p = alpha * occurred + (1.0 - alpha) * p
        if y[t] > 0:
            z = beta * float(y[t]) + (1.0 - beta) * z
    return float(p), float(z)


def tsb(train: Sequence[float], horizon: int, alpha: float = 0.1, beta: float = 0.1) -> List[float]:
    """Teunter-Syntetos-Babai — smooths demand PROBABILITY every period.

    alpha updates the non-zero-demand probability; beta updates the demand size.
    Handles obsolescence (demand that stops) better than Croston, which never
    updates its rate during a run of zeros.
    """
    p, z = _tsb_components(train, alpha, beta)
    return [float(p * z)] * horizon


def naive_last(train: Sequence[float], horizon: int) -> List[float]:
    """Repeat the last observed value — the canonical cheap baseline."""
    y = np.asarray(train, dtype=float)
    last = float(y[-1]) if y.size else 0.0
    return [last] * horizon


def mase(
    train: Sequence[float],
    actuals: Sequence[float],
    forecasts: Sequence[float],
    seasonality: int = 1,
) -> float:
    """Mean Absolute Scaled Error.

    Denominator = MAE of the in-sample seasonal-naive one-step forecast
    (y_t vs y_{t-seasonality}). Returns NaN when that denominator is 0
    (undefined — caller should skip the series).
    """
    tr = np.asarray(train, dtype=float)
    a = np.asarray(actuals, dtype=float)
    f = np.asarray(forecasts, dtype=float)
    if tr.size <= seasonality:
        return float("nan")
    denom = np.mean(np.abs(tr[seasonality:] - tr[:-seasonality]))
    if denom == 0:
        return float("nan")
    return float(np.mean(np.abs(a - f)) / denom)


def rmsse(
    train: Sequence[float],
    actuals: Sequence[float],
    forecasts: Sequence[float],
) -> float:
    """Root Mean Squared Scaled Error (M5 competition metric).

    Denominator = MSE of the in-sample naive one-step forecast (y_t vs y_{t-1}).
    Returns NaN when that denominator is 0 (undefined — caller should skip).
    """
    tr = np.asarray(train, dtype=float)
    a = np.asarray(actuals, dtype=float)
    f = np.asarray(forecasts, dtype=float)
    if tr.size < 2:
        return float("nan")
    denom = np.mean((tr[1:] - tr[:-1]) ** 2)
    if denom == 0:
        return float("nan")
    return float(np.sqrt(np.mean((a - f) ** 2) / denom))


# ─────────────────────────────────────────────────────────────────────────────
# Predictive distributions
#
# Everything below returns a pmf over the counts 0, 1, 2, ..., K as a 1-D numpy
# array of length K+1 that sums to 1. The support K is chosen per distribution so
# the truncated tail mass is < TAIL_MASS_TOL; `crps_discrete` extends the cdf with
# 1.0 beyond K, so an observation outside the support is still scored correctly.
# ─────────────────────────────────────────────────────────────────────────────

#: Largest tail mass we are willing to fold away when truncating a count support.
TAIL_MASS_TOL = 1e-10
#: Support bounds. The floor keeps small supports cheap to score; the cap stops a
#: pathological (huge-mean) series from allocating an unbounded array.
_MIN_SUPPORT = 32
_MAX_SUPPORT = 4096


def point_mass(k: int, min_len: int = 1) -> np.ndarray:
    """pmf degenerate at the non-negative integer `k`.

    Public because any point forecaster can be lifted into this module's
    distributional interface by wrapping its output in one of these — that is how
    Prophet is scored in `seeds/run_carparts_backtest.py`.
    """
    k = max(0, int(k))
    pmf = np.zeros(max(k + 1, min_len), dtype=float)
    pmf[k] = 1.0
    return pmf


def _size_shape(train: Sequence[float]) -> float:
    """Negative-binomial shape r for the ORDER SIZE, from the non-zero training values.

    Returns `inf` (the Poisson limit) unless the non-zero sizes are overdispersed
    (sample variance > sample mean), which is the minority case on real spare-parts
    panels — see the module docstring for the measured figures. The estimator is the
    method-of-moments plug-in r = m^2 / (v - m) applied to the truncated sample; see
    the module docstring for why that approximation is acceptable here.
    """
    y = np.asarray(train, dtype=float)
    sizes = y[y > 0]
    if sizes.size < 3:
        return math.inf
    m = float(sizes.mean())
    v = float(sizes.var(ddof=1))
    if not np.isfinite(v) or v <= m or m <= 0:
        return math.inf
    return m * m / (v - m)


def _nb_pmf(mean: float, shape: float, k_max: int) -> np.ndarray:
    """Negative-binomial pmf on 0..k_max (Poisson when `shape` is inf).

    Built by the stable forward recursion P(k) = P(k-1) * (k-1+r)/k * mean/(mean+r)
    (Poisson limit: P(k) = P(k-1) * mean/k), which avoids gamma functions entirely.
    """
    ks = np.arange(1, k_max + 1, dtype=float)
    if not np.isfinite(shape):
        p0 = math.exp(-mean)
        ratios = mean / ks
    else:
        p0 = math.exp(shape * (math.log(shape) - math.log(shape + mean)))
        ratios = (ks - 1.0 + shape) / ks * (mean / (mean + shape))
    pmf = np.empty(k_max + 1, dtype=float)
    pmf[0] = p0
    pmf[1:] = p0 * np.cumprod(ratios)
    return pmf


def _ztnb_mean(mean: float, shape: float) -> float:
    """Mean of the ZERO-TRUNCATED NB with untruncated mean `mean` and shape `shape`."""
    if not np.isfinite(shape):
        p0 = math.exp(-mean)
    else:
        p0 = math.exp(shape * (math.log(shape) - math.log(shape + mean)))
    if p0 >= 1.0 - 1e-15:
        return 1.0
    return mean / (1.0 - p0)


def _size_pmf(target_mean: float, shape: float) -> np.ndarray:
    """Zero-truncated NB pmf on 1..K whose mean equals `target_mean`.

    `target_mean` is the CONDITIONAL mean order size given that an order occurs, so
    it is >= 1 by definition. The untruncated mean that produces it is recovered by
    bisection — `_ztnb_mean` is strictly increasing in `mean`, so the solve is
    unconditionally well-posed.
    """
    if not np.isfinite(target_mean) or target_mean <= 1.0 + 1e-12:
        return point_mass(1)

    lo, hi = 1e-9, max(target_mean, 1.0)
    while _ztnb_mean(hi, shape) < target_mean and hi < 1e9:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _ztnb_mean(mid, shape) < target_mean:
            lo = mid
        else:
            hi = mid
    mu = 0.5 * (lo + hi)

    k_max = _MIN_SUPPORT
    while True:
        full = _nb_pmf(mu, shape, k_max)         # untruncated, on 0..k_max
        tail = max(0.0, 1.0 - float(full.sum()))  # untruncated mass beyond k_max
        pmf = full.copy()
        pmf[0] = 0.0                              # zero-truncation
        total = float(pmf.sum())
        if total <= 0:
            return point_mass(1)
        if tail / total < TAIL_MASS_TOL or k_max >= _MAX_SUPPORT:
            return pmf / total
        k_max = min(k_max * 4, _MAX_SUPPORT)


def _compound_bernoulli(p: float, size_pmf: np.ndarray) -> np.ndarray:
    """pmf of Y = B * S with B ~ Bernoulli(p) and S the (strictly positive) size.

    P(Y = 0) = 1 - p exactly, because `size_pmf` has no mass at 0.
    """
    p = float(min(max(p, 0.0), 1.0))
    if p <= 0.0:
        return point_mass(0, min_len=len(size_pmf))
    pmf = p * np.asarray(size_pmf, dtype=float)
    pmf[0] = 1.0 - p
    return pmf


def croston_dist(train: Sequence[float], horizon: int, alpha: float = 0.1) -> List[np.ndarray]:
    """Croston as a compound-Bernoulli predictive distribution, flat over the horizon.

    ASSUMPTION: memoryless (Bernoulli) arrivals, so Croston's smoothed inter-arrival
    interval p_hat is the mean of a Geometric law and the per-period occurrence
    probability is 1 / p_hat. See the module docstring.
    """
    parts = _croston_components(train, alpha)
    if parts is None:
        return [point_mass(0)] * horizon
    z_hat, interval_hat = parts
    pmf = _compound_bernoulli(1.0 / interval_hat, _size_pmf(z_hat, _size_shape(train)))
    return [pmf] * horizon


def sba_dist(train: Sequence[float], horizon: int, alpha: float = 0.1) -> List[np.ndarray]:
    """SBA as a compound-Bernoulli predictive distribution, flat over the horizon.

    ASSUMPTION: the (1 - alpha/2) Syntetos-Boylan factor corrects the OCCURRENCE
    PROBABILITY, since that is where the inverse-interval Jensen bias lives; the
    size estimator is unbiased and is left alone. See the module docstring.
    """
    parts = _croston_components(train, alpha)
    if parts is None:
        return [point_mass(0)] * horizon
    z_hat, interval_hat = parts
    p = (1.0 - alpha / 2.0) / interval_hat
    pmf = _compound_bernoulli(p, _size_pmf(z_hat, _size_shape(train)))
    return [pmf] * horizon


def tsb_dist(
    train: Sequence[float], horizon: int, alpha: float = 0.1, beta: float = 0.1
) -> List[np.ndarray]:
    """TSB as a compound-Bernoulli predictive distribution, flat over the horizon.

    ASSUMPTION: none beyond the compound-Bernoulli structure — TSB already estimates
    an occurrence probability and a conditional size, so this is its native form.
    """
    p, z = _tsb_components(train, alpha, beta)
    if p <= 0.0 or z <= 0.0:
        return [point_mass(0)] * horizon
    pmf = _compound_bernoulli(p, _size_pmf(z, _size_shape(train)))
    return [pmf] * horizon


def naive_last_dist(train: Sequence[float], horizon: int) -> List[np.ndarray]:
    """The naive point forecast, degenerate: all mass on the last observed value.

    Zero spread is the point, not an oversight — it is what "repeat the last number"
    asserts, and it makes CRPS collapse to absolute error (so scaled CRPS collapses
    to MASE), giving the point and distributional leaderboards a shared anchor.
    """
    y = np.asarray(train, dtype=float)
    last = int(round(float(y[-1]))) if y.size else 0
    return [point_mass(last)] * horizon


def zero_dist(train: Sequence[float], horizon: int) -> List[np.ndarray]:
    """Degenerate at 0 — the conditional median of most intermittent series.

    Included so the claim "a MASE leaderboard can reward a degenerate near-zero
    forecast" is a measurement rather than an assertion.
    """
    del train
    return [point_mass(0)] * horizon


def climatology_dist(train: Sequence[float], horizon: int) -> List[np.ndarray]:
    """The in-sample EMPIRICAL distribution of the training window.

    ASSUMPTION: the training window is exchangeable with the test window (no trend,
    no obsolescence). The standard probabilistic reference forecast.
    """
    y = np.asarray(train, dtype=float)
    if y.size == 0:
        return [point_mass(0)] * horizon
    counts = np.rint(np.clip(y, 0.0, None)).astype(int)
    k_max = int(counts.max())
    pmf = np.bincount(counts, minlength=k_max + 1).astype(float)
    return [pmf / pmf.sum()] * horizon


# ─────────────────────────────────────────────────────────────────────────────
# Scaled distributional errors — SAME training-only denominator as MASE, so a
# distributional score sits on the identical scale as the point score and the two
# leaderboards are directly comparable.
# ─────────────────────────────────────────────────────────────────────────────


def mase_denominator(train: Sequence[float], seasonality: int = 1) -> float:
    """MAE of the in-sample seasonal-naive one-step forecast. NaN when undefined.

    Exposed because the distributional scores below must divide by *exactly* this
    quantity to be comparable with MASE, and because it is computed from the
    TRAINING window only — never from the held-out actuals.
    """
    tr = np.asarray(train, dtype=float)
    if tr.size <= seasonality:
        return float("nan")
    denom = float(np.mean(np.abs(tr[seasonality:] - tr[:-seasonality])))
    return float("nan") if denom == 0 else denom


def scaled_crps(
    train: Sequence[float],
    actuals: Sequence[float],
    dists: Sequence[Sequence[float]],
    seasonality: int = 1,
) -> float:
    """Mean CRPS over the horizon, scaled by the MASE denominator.

    Because CRPS of a degenerate distribution is absolute error, `scaled_crps` of a
    degenerate forecast equals `mase` of the same point forecast exactly — asserted
    in the tests. Lower is better; NaN when the denominator is undefined.
    """
    denom = mase_denominator(train, seasonality)
    if not np.isfinite(denom):
        return float("nan")
    a = np.asarray(actuals, dtype=float)
    if len(dists) != a.size:
        raise ValueError(f"got {len(dists)} distributions for {a.size} actuals")
    scores = [crps_discrete(d, float(y)) for d, y in zip(dists, a, strict=True)]
    return float(np.mean(scores) / denom)


def scaled_pinball(
    train: Sequence[float],
    actuals: Sequence[float],
    dists: Sequence[Sequence[float]],
    seasonality: int = 1,
    levels: Sequence[float] = DEFAULT_QUANTILE_LEVELS,
) -> float:
    """Mean pinball loss over the horizon and quantile grid, scaled like MASE.

    The M5 "Uncertainty" track's scaled pinball loss (SPL). Lower is better; NaN
    when the denominator is undefined.
    """
    denom = mase_denominator(train, seasonality)
    if not np.isfinite(denom):
        return float("nan")
    a = np.asarray(actuals, dtype=float)
    if len(dists) != a.size:
        raise ValueError(f"got {len(dists)} distributions for {a.size} actuals")
    scores = [mean_pinball_loss(d, float(y), levels) for d, y in zip(dists, a, strict=True)]
    return float(np.mean(scores) / denom)
