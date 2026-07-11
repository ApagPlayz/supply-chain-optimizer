"""Per-SKU intermittent-demand backtest on the REAL Monash Car Parts dataset.

Demonstrates the per-item forecasting technique real component/spare-part planners
use — Croston-family estimators — against the cheap naive baseline and the
Prophet/ML approach the app serves. Protocol matches the Monash benchmark:

  * 2,674 real monthly SKU series (51 months each), missing -> 0.
  * Single train/test split per series: last HORIZON=12 months held out.
  * Metrics per series: MASE (vs in-sample seasonal-naive) and RMSSE (M5), then
    aggregated (mean + median) across all series. Series whose in-sample naive
    denominator is 0 are skipped as undefined (reported as `skipped`).
  * Prophet is slow (per-series fit) so it is scored on a fixed random SAMPLE of
    series and clearly labelled as such — the point is a like-for-like read on the
    ML approach, not to re-run 2,674 Prophet fits.

Usage:
    cd backend
    python -m seeds.run_carparts_backtest [--sample 150] [--no-prophet]

Writes seeds/data/carparts_backtest.json (metrics only — no fabricated data).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Callable, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HORIZON = 12
SEASONALITY = 12  # monthly
OUT_PATH = Path(__file__).resolve().parent / "data" / "carparts_backtest.json"


def _prophet_fit_predict(train: np.ndarray, horizon: int) -> List[float]:
    """Prophet point forecast, non-negative-clamped (demand can't be < 0)."""
    import pandas as pd
    from prophet import Prophet

    ds = pd.date_range("1998-01-01", periods=len(train), freq="MS")
    df = pd.DataFrame({"ds": ds, "y": [float(v) for v in train]})
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        uncertainty_samples=0,
    )
    m.fit(df)
    future = m.make_future_dataframe(periods=horizon, freq="MS", include_history=False)
    yhat = m.predict(future)["yhat"].to_numpy()
    return [max(0.0, float(v)) for v in yhat]


def _aggregate(vals: List[float]) -> Dict[str, float]:
    arr = np.asarray([v for v in vals if np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return {"mean": float("nan"), "median": float("nan"), "n": 0}
    return {
        "mean": round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "n": int(arr.size),
    }


def backtest_method(
    mat: np.ndarray,
    method: Callable[[np.ndarray], List[float]],
    idx: np.ndarray,
) -> Dict[str, Dict[str, float]]:
    """Run one method over the selected series indices; return aggregated metrics."""
    from app.ml.intermittent import mase, rmsse

    mase_vals: List[float] = []
    rmsse_vals: List[float] = []
    skipped = 0
    for i in idx:
        series = mat[i]
        train, test = series[:-HORIZON], series[-HORIZON:]
        preds = method(train)
        mv = mase(train, test, preds, seasonality=SEASONALITY)
        rv = rmsse(train, test, preds)
        if not np.isfinite(mv) and not np.isfinite(rv):
            skipped += 1
            continue
        if np.isfinite(mv):
            mase_vals.append(mv)
        if np.isfinite(rv):
            rmsse_vals.append(rv)
    return {
        "mase": _aggregate(mase_vals),
        "rmsse": _aggregate(rmsse_vals),
        "skipped_undefined": skipped,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=150, help="series count for the slow Prophet run")
    ap.add_argument("--no-prophet", action="store_true", help="skip the Prophet comparison")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from seeds.monash_loader import as_matrix, load_car_parts
    from app.ml.intermittent import croston, naive_last, sba, tsb

    series = load_car_parts(refresh=True)
    names, mat = as_matrix(series)
    n = mat.shape[0]
    nonzero_frac = float((mat > 0).mean())
    logger.info(
        "Loaded %d Monash car-parts series x %d months (nonzero fraction=%.1f%%)",
        n, mat.shape[1], nonzero_frac * 100,
    )

    all_idx = np.arange(n)
    fast_methods: Dict[str, Callable[[np.ndarray], List[float]]] = {
        "naive_last": lambda tr: naive_last(tr, HORIZON),
        "croston": lambda tr: croston(tr, HORIZON),
        "sba": lambda tr: sba(tr, HORIZON),
        "tsb": lambda tr: tsb(tr, HORIZON),
    }

    results: Dict[str, dict] = {}
    for name, fn in fast_methods.items():
        logger.info("Backtesting %s on all %d series...", name, n)
        results[name] = backtest_method(mat, fn, all_idx)
        logger.info(
            "  %s: MASE mean=%.3f median=%.3f | RMSSE mean=%.3f median=%.3f",
            name, results[name]["mase"]["mean"], results[name]["mase"]["median"],
            results[name]["rmsse"]["mean"], results[name]["rmsse"]["median"],
        )

    prophet_sample_idx = None
    if not args.no_prophet:
        rng = np.random.default_rng(args.seed)
        k = min(args.sample, n)
        prophet_sample_idx = np.sort(rng.choice(all_idx, size=k, replace=False))
        logging.getLogger("prophet").setLevel(logging.WARNING)
        logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
        logger.info("Backtesting Prophet on a %d-series sample (slow, per-series fit)...", k)
        results["prophet_sample"] = backtest_method(
            mat, lambda tr: _prophet_fit_predict(tr, HORIZON), prophet_sample_idx
        )
        # Fair comparison: re-score the fast methods on the SAME sample.
        for name, fn in fast_methods.items():
            results[f"{name}_on_prophet_sample"] = backtest_method(mat, fn, prophet_sample_idx)
        logger.info(
            "  prophet(sample): MASE mean=%.3f median=%.3f | RMSSE mean=%.3f median=%.3f",
            results["prophet_sample"]["mase"]["mean"], results["prophet_sample"]["mase"]["median"],
            results["prophet_sample"]["rmsse"]["mean"], results["prophet_sample"]["rmsse"]["median"],
        )

    payload = {
        "dataset": "monash_car_parts_with_missing_values",
        "source": "HuggingFace Monash-University/monash_tsf",
        "n_series": n,
        "series_length": int(mat.shape[1]),
        "nonzero_fraction": round(nonzero_frac, 4),
        "horizon": HORIZON,
        "seasonality": SEASONALITY,
        "protocol": "single split, last HORIZON held out; MASE/RMSSE vs in-sample naive",
        "prophet_sample_size": int(len(prophet_sample_idx)) if prophet_sample_idx is not None else 0,
        "results": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    logger.info("DONE — wrote %s", OUT_PATH)


if __name__ == "__main__":
    main()
