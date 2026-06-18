"""
Forecast accuracy metrics for demand-forecast evaluation.

These are the metrics supply-chain forecasting teams actually report (not just a
single MAPE). All functions take two equal-length sequences (actuals, forecasts)
and return a float. They are pure and dependency-light (numpy only) so they can be
unit-tested directly and reused by the walk-forward backtest harness.

  WAPE  — Weighted Absolute Percentage Error = Σ|a−f| / Σ|a|. Preferred over MAPE
          for intermittent/low-volume demand because it does not blow up on zeros.
  MAPE  — Mean Absolute Percentage Error (reported for comparability; zero-guarded).
  RMSE  — Root Mean Squared Error (penalises large misses).
  bias  — Mean Error = mean(f − a). Positive ⇒ systematic over-forecast.
  MAD   — Mean Absolute Deviation = mean(|a − f|).
  tracking_signal — Σ(f − a) / MAD. |TS| > ~4 signals a model that is drifting and
          should be re-fit (classic supply-chain control-limit heuristic).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

__all__ = [
    "wape",
    "mape",
    "rmse",
    "bias",
    "mad",
    "tracking_signal",
    "all_metrics",
]


def _arrays(actuals: Sequence[float], forecasts: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(actuals, dtype=float)
    f = np.asarray(forecasts, dtype=float)
    if a.shape != f.shape:
        raise ValueError(f"actuals/forecasts length mismatch: {a.shape} vs {f.shape}")
    if a.size == 0:
        raise ValueError("cannot compute metrics on empty input")
    return a, f


def wape(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    a, f = _arrays(actuals, forecasts)
    denom = np.sum(np.abs(a))
    if denom == 0:
        return 0.0 if np.sum(np.abs(f)) == 0 else float("inf")
    return float(np.sum(np.abs(a - f)) / denom)


def mape(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    a, f = _arrays(actuals, forecasts)
    # Zero-guard: ignore points where the actual is exactly zero (undefined percentage).
    mask = a != 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((a[mask] - f[mask]) / a[mask])))


def rmse(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    a, f = _arrays(actuals, forecasts)
    return float(np.sqrt(np.mean((a - f) ** 2)))


def bias(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    """Mean error (forecast − actual). Positive ⇒ over-forecasting."""
    a, f = _arrays(actuals, forecasts)
    return float(np.mean(f - a))


def mad(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    a, f = _arrays(actuals, forecasts)
    return float(np.mean(np.abs(a - f)))


def tracking_signal(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    """Cumulative error / MAD. Zero when MAD is zero (perfect forecast)."""
    a, f = _arrays(actuals, forecasts)
    m = np.mean(np.abs(a - f))
    if m == 0:
        return 0.0
    return float(np.sum(f - a) / m)


def all_metrics(actuals: Sequence[float], forecasts: Sequence[float]) -> dict[str, float]:
    """Return every metric as a dict — convenient for backtest aggregation/logging."""
    return {
        "wape": wape(actuals, forecasts),
        "mape": mape(actuals, forecasts),
        "rmse": rmse(actuals, forecasts),
        "bias": bias(actuals, forecasts),
        "mad": mad(actuals, forecasts),
        "tracking_signal": tracking_signal(actuals, forecasts),
    }
