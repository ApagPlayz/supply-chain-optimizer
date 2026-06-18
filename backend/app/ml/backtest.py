"""
Walk-forward (rolling-origin) backtesting for demand forecasts.

A single train/test split with one MAPE is the most common portfolio-project
failure. This harness instead retrains at several origins and reports how accuracy
degrades across the forecast horizon — the question a real forecasting reviewer asks
("where is the model reliable, and where does it fall apart?").

Design:
  - The series' last `n_windows * horizon` points form the out-of-sample region,
    split into `n_windows` consecutive, non-overlapping blocks of length `horizon`.
  - For each window the model is fit on everything strictly before the block, then
    asked to predict `horizon` steps. Predictions are compared to the held-out block.
  - Errors are bucketed BY HORIZON STEP (1..horizon) so we can report accuracy
    degradation, plus an overall roll-up.

The forecasting model is injected as `fit_predict(train_values) -> list[float]`
(length == horizon), so the harness is model-agnostic and unit-testable without
Prophet. `train_forecasts.py` passes a Prophet-backed callable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Sequence

from app.ml import forecast_metrics as fm

# A model: given the training values, return `horizon` future point forecasts.
FitPredict = Callable[[Sequence[float]], Sequence[float]]


@dataclass
class HorizonMetrics:
    """Metrics at one forecast step (or the overall roll-up when horizon == 0)."""
    horizon: int
    n: int
    wape: float
    mape: float
    rmse: float
    bias: float
    tracking_signal: float

    def as_dict(self) -> dict:
        return {
            "horizon": self.horizon,
            "n": self.n,
            "wape": round(self.wape, 4),
            "mape": round(self.mape, 4),
            "rmse": round(self.rmse, 4),
            "bias": round(self.bias, 4),
            "tracking_signal": round(self.tracking_signal, 4),
        }


@dataclass
class BacktestReport:
    n_windows: int
    horizon: int
    train_sizes: List[int] = field(default_factory=list)
    per_horizon: List[HorizonMetrics] = field(default_factory=list)
    overall: HorizonMetrics | None = None

    def as_dict(self) -> dict:
        return {
            "method": "walk_forward_rolling_origin",
            "n_windows": self.n_windows,
            "horizon": self.horizon,
            "train_sizes": self.train_sizes,
            "overall": self.overall.as_dict() if self.overall else None,
            "by_horizon": [h.as_dict() for h in self.per_horizon],
        }


def _metrics_at(horizon: int, actuals: List[float], forecasts: List[float]) -> HorizonMetrics:
    m = fm.all_metrics(actuals, forecasts)
    return HorizonMetrics(
        horizon=horizon,
        n=len(actuals),
        wape=m["wape"],
        mape=m["mape"],
        rmse=m["rmse"],
        bias=m["bias"],
        tracking_signal=m["tracking_signal"],
    )


def walk_forward_backtest(
    series: Sequence[float],
    fit_predict: FitPredict,
    horizon: int = 12,
    n_windows: int = 3,
    min_train: int | None = None,
) -> BacktestReport:
    """Run a rolling-origin backtest and return per-horizon + overall metrics.

    Args:
        series: the full historical series (chronological).
        fit_predict: model callable; receives train values, returns `horizon` forecasts.
        horizon: forecast steps per window.
        n_windows: number of rolling origins (non-overlapping test blocks).
        min_train: minimum training points required before the first window. Defaults
            to one horizon, so the first fold always trains on at least `horizon` points.

    Raises:
        ValueError if the series is too short for the requested windows/horizon.
    """
    values = [float(v) for v in series]
    n = len(values)
    if horizon < 1 or n_windows < 1:
        raise ValueError("horizon and n_windows must be >= 1")

    min_train = min_train if min_train is not None else horizon
    needed = min_train + n_windows * horizon
    if n < needed:
        raise ValueError(
            f"series too short for backtest: have {n}, need >= {needed} "
            f"(min_train={min_train} + n_windows={n_windows} * horizon={horizon})"
        )

    test_start = n - n_windows * horizon  # first index of the held-out region

    # Bucket (actual, forecast) pairs by horizon step (0-indexed internally).
    by_step: List[tuple[List[float], List[float]]] = [([], []) for _ in range(horizon)]
    all_actual: List[float] = []
    all_forecast: List[float] = []
    train_sizes: List[int] = []

    for w in range(n_windows):
        cut = test_start + w * horizon
        train = values[:cut]
        actual_block = values[cut:cut + horizon]
        train_sizes.append(len(train))

        preds = list(fit_predict(train))
        if len(preds) != horizon:
            raise ValueError(
                f"fit_predict returned {len(preds)} forecasts, expected horizon={horizon}"
            )

        for step in range(horizon):
            by_step[step][0].append(actual_block[step])
            by_step[step][1].append(preds[step])
            all_actual.append(actual_block[step])
            all_forecast.append(preds[step])

    per_horizon = [
        _metrics_at(step + 1, acts, fcsts) for step, (acts, fcsts) in enumerate(by_step)
    ]
    overall = _metrics_at(0, all_actual, all_forecast)

    return BacktestReport(
        n_windows=n_windows,
        horizon=horizon,
        train_sizes=train_sizes,
        per_horizon=per_horizon,
        overall=overall,
    )
