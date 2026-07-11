"""Intermittent-demand forecasting methods + scaled-error metrics.

Component/spare-part demand is *intermittent*: long runs of zero interrupted by
small, sporadic orders. Ordinary exponential smoothing / Prophet are known to be
biased on this pattern, so real component planners use Croston-family estimators.
This module implements the three that matter, plus the two scaled-error metrics
(MASE, RMSSE) the M-competitions and Monash benchmarks report — none of which
require a heavy dependency (numpy only, same as forecast_metrics.py).

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
"""
from __future__ import annotations

from typing import List, Sequence

import numpy as np

__all__ = [
    "croston",
    "sba",
    "tsb",
    "naive_last",
    "mase",
    "rmsse",
]


def _ses_recursion(values: np.ndarray, alpha: float) -> float:
    """Return the final level of a simple-exponential-smoothing pass."""
    level = float(values[0])
    for v in values[1:]:
        level = alpha * float(v) + (1.0 - alpha) * level
    return level


def croston(train: Sequence[float], horizon: int, alpha: float = 0.1) -> List[float]:
    """Croston's method — flat rate forecast repeated over the horizon.

    Falls back to the series mean when there are no non-zero demands (nothing to
    decompose) so the forecast is always defined.
    """
    y = np.asarray(train, dtype=float)
    nz_idx = np.flatnonzero(y > 0)
    if nz_idx.size == 0:
        return [0.0] * horizon
    if nz_idx.size == 1:
        rate = float(y[nz_idx[0]]) / float(len(y))
        return [rate] * horizon

    sizes = y[nz_idx]
    intervals = np.diff(np.concatenate([[-1], nz_idx])).astype(float)  # gap incl. first
    z_hat = _ses_recursion(sizes, alpha)         # smoothed demand size
    p_hat = _ses_recursion(intervals, alpha)     # smoothed inter-arrival interval
    rate = z_hat / p_hat if p_hat > 0 else z_hat
    return [float(rate)] * horizon


def sba(train: Sequence[float], horizon: int, alpha: float = 0.1) -> List[float]:
    """Syntetos-Boylan Approximation — bias-corrected Croston."""
    base = croston(train, horizon, alpha)[0]
    return [float(base * (1.0 - alpha / 2.0))] * horizon


def tsb(train: Sequence[float], horizon: int, alpha: float = 0.1, beta: float = 0.1) -> List[float]:
    """Teunter-Syntetos-Babai — smooths demand PROBABILITY every period.

    alpha updates the non-zero-demand probability; beta updates the demand size.
    Handles obsolescence (demand that stops) better than Croston, which never
    updates its rate during a run of zeros.
    """
    y = np.asarray(train, dtype=float)
    if y.size == 0:
        return [0.0] * horizon
    nz = y > 0
    p = float(nz.mean()) if nz.any() else 0.0            # demand probability
    z = float(y[nz].mean()) if nz.any() else 0.0         # demand size
    for t in range(len(y)):
        occurred = 1.0 if y[t] > 0 else 0.0
        p = alpha * occurred + (1.0 - alpha) * p
        if y[t] > 0:
            z = beta * float(y[t]) + (1.0 - beta) * z
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
