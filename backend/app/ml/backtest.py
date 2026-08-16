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
Prophet. `seeds/run_forecast_backtest.py` passes a Prophet-backed callable.

`rolling_origins` below is the split itself, factored out so that anything wanting
this protocol runs the SAME code rather than a lookalike — `seeds/run_carparts_backtest.py`
scores predictive distributions, which this point-forecast harness cannot express,
but it places its origins with this function so the two backtests cannot drift.
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
class Fold:
    """One backtest origin: what the model may train on, and what it is scored against.

    Separating the fold from the series is what makes a REAL-TIME backtest expressible.
    In the pseudo-real-time protocol every fold slices the same (latest, fully revised)
    series. In the real-time protocol each fold's ``train`` comes from the data vintage
    that actually existed at that origin, while ``actual`` still comes from one common
    reference vintage — so the models are compared on identical targets and the only
    thing that changes is the information set they were given.
    """

    train: List[float]
    actual: List[float]
    label: str | None = None

    def as_dict(self) -> dict:
        return {"label": self.label, "n_train": len(self.train), "n_actual": len(self.actual)}


@dataclass
class BacktestReport:
    n_windows: int
    horizon: int
    train_sizes: List[int] = field(default_factory=list)
    per_horizon: List[HorizonMetrics] = field(default_factory=list)
    overall: HorizonMetrics | None = None
    method: str = "walk_forward_rolling_origin"
    per_window: List[dict] = field(default_factory=list)
    abs_errors: List[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "n_windows": self.n_windows,
            "horizon": self.horizon,
            "train_sizes": self.train_sizes,
            "overall": self.overall.as_dict() if self.overall else None,
            "by_horizon": [h.as_dict() for h in self.per_horizon],
            # Per-origin roll-ups. With only 3 origins the overall WAPE hides whether a
            # model won consistently or won once; a sign flip across origins is the
            # cheapest honest evidence that a headline gap is not a reliable difference.
            "per_window": self.per_window,
        }


def rolling_origins(
    n: int,
    horizon: int,
    n_windows: int,
    min_train: int | None = None,
) -> List[int]:
    """Return the training cut-points of a rolling-origin split.

    The single source of truth for "where do the origins go", so any harness that
    calls it is running the *same* protocol rather than a re-implementation that
    happens to look similar. Cut `c` means: train on values[:c], predict
    values[c:c+horizon]. Blocks are consecutive and non-overlapping and the last
    one ends exactly at the end of the series.

    Args:
        n: length of the full series.
        horizon: forecast steps per window.
        n_windows: number of rolling origins.
        min_train: minimum training points before the first origin. Defaults to one
            horizon.

    Raises:
        ValueError if the series is too short for the requested split.
    """
    if horizon < 1 or n_windows < 1:
        raise ValueError("horizon and n_windows must be >= 1")
    min_train = min_train if min_train is not None else horizon
    needed = min_train + n_windows * horizon
    if n < needed:
        raise ValueError(
            f"series too short for backtest: have {n}, need >= {needed} "
            f"(min_train={min_train} + n_windows={n_windows} * horizon={horizon})"
        )
    test_start = n - n_windows * horizon
    return [test_start + w * horizon for w in range(n_windows)]


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
    cuts = rolling_origins(len(values), horizon, n_windows, min_train)
    folds = [
        Fold(train=values[:cut], actual=values[cut:cut + horizon], label=f"cut={cut}")
        for cut in cuts
    ]
    return backtest_folds(folds, fit_predict, horizon=horizon)


def backtest_folds(
    folds: Sequence[Fold],
    fit_predict: FitPredict,
    horizon: int = 12,
    method: str = "walk_forward_rolling_origin",
) -> BacktestReport:
    """Score a model over explicit folds — the shared engine of every protocol here.

    `walk_forward_backtest` builds its folds by slicing one series; the real-time
    protocol builds them from per-origin data vintages. Both then run THIS function, so
    the metrics, the horizon bucketing and the roll-up cannot drift between protocols.
    """
    # Bucket (actual, forecast) pairs by horizon step (0-indexed internally).
    by_step: List[tuple[List[float], List[float]]] = [([], []) for _ in range(horizon)]
    all_actual: List[float] = []
    all_forecast: List[float] = []
    train_sizes: List[int] = []
    per_window: List[dict] = []
    abs_errors: List[float] = []

    for fold in folds:
        if len(fold.actual) != horizon:
            raise ValueError(
                f"fold {fold.label!r} has {len(fold.actual)} actuals, expected horizon={horizon}"
            )
        train_sizes.append(len(fold.train))

        preds = list(fit_predict(fold.train))
        if len(preds) != horizon:
            raise ValueError(
                f"fit_predict returned {len(preds)} forecasts, expected horizon={horizon}"
            )

        for step in range(horizon):
            by_step[step][0].append(fold.actual[step])
            by_step[step][1].append(preds[step])
            all_actual.append(fold.actual[step])
            all_forecast.append(preds[step])
            abs_errors.append(abs(preds[step] - fold.actual[step]))

        win = _metrics_at(0, list(fold.actual), preds).as_dict()
        win.update(fold.as_dict())
        per_window.append(win)

    per_horizon = [
        _metrics_at(step + 1, acts, fcsts) for step, (acts, fcsts) in enumerate(by_step)
    ]
    overall = _metrics_at(0, all_actual, all_forecast)

    return BacktestReport(
        n_windows=len(folds),
        horizon=horizon,
        train_sizes=train_sizes,
        per_horizon=per_horizon,
        overall=overall,
        method=method,
        per_window=per_window,
        abs_errors=abs_errors,
    )
