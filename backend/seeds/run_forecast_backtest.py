"""
Walk-forward backtest of the demand forecaster on REAL data, vs a baseline.

Answers the question a forecasting reviewer actually asks: "does Prophet beat a
naive baseline on real semiconductor demand, and where does it degrade across
the horizon?" — not "what's one MAPE on one split?".

Source series: FRED IPG3344S (Industrial Production: Semiconductors), monthly,
fetched keyless via fredgraph CSV (cached in seeds/data/). Two models are run
through the same rolling-origin harness:

  * Prophet            — yearly-seasonal additive model
  * seasonal-naive (m=12) — repeat the value from 12 months ago (the standard
                            cheap baseline Prophet must beat to justify itself)

Skill score = 1 - WAPE(prophet) / WAPE(naive). Positive ⇒ Prophet adds value.

Usage:
    cd backend
    python -m seeds.run_forecast_backtest

Writes docs/FORECAST_BACKTEST.md and docs/forecast_backtest.json (repo root).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import List, Sequence

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HORIZON = 12        # months
N_WINDOWS = 3       # rolling origins
SEASONAL_PERIOD = 12
ANCHOR_DATE = "2000-01-01"   # synthetic monthly axis for Prophet (only spacing matters)


def seasonal_naive_fit_predict(train: Sequence[float]) -> List[float]:
    """Forecast = the observation SEASONAL_PERIOD steps back (last year, same month).

    Falls back to the last observed value when there isn't a full season of
    history yet. This is the canonical baseline for seasonal monthly demand.
    """
    vals = list(train)
    out: List[float] = []
    for h in range(1, HORIZON + 1):
        ref = len(vals) - SEASONAL_PERIOD + ((h - 1) % SEASONAL_PERIOD)
        out.append(vals[ref] if ref >= 0 else vals[-1])
    return out


def make_prophet_fit_predict():
    """Build a Prophet-backed fit_predict callable (lazy import; quiet logging)."""
    import pandas as pd
    from prophet import Prophet

    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    def fit_predict(train: Sequence[float]) -> List[float]:
        n = len(train)
        ds = pd.date_range(ANCHOR_DATE, periods=n, freq="MS")
        df = pd.DataFrame({"ds": ds, "y": list(train)})
        m = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            uncertainty_samples=0,   # point forecasts only — faster, bounds not needed here
        )
        m.fit(df)
        future = m.make_future_dataframe(periods=HORIZON, freq="MS", include_history=False)
        forecast = m.predict(future)
        return [float(v) for v in forecast["yhat"].tolist()]

    return fit_predict


def _load_series() -> "pd.Series":  # noqa: F821 (pandas imported lazily)
    """Load real IPG3344S — refresh from FRED (keyless) and update the cache."""
    from seeds.train_forecasts import CACHE_PATH, FRED_DEMAND_SERIES
    from app.ml.fred_client import fetch_fred_series_csv
    import pandas as pd

    series = fetch_fred_series_csv(FRED_DEMAND_SERIES, start="2010-01-01")
    if series is not None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        series.to_frame().to_csv(CACHE_PATH, index_label="observation_date")
        logger.info("Fetched %s live (%d obs)", FRED_DEMAND_SERIES, len(series))
        return series
    if not CACHE_PATH.exists():
        logger.error("No live FRED access and no cache at %s — cannot backtest.", CACHE_PATH)
        sys.exit(1)
    df = pd.read_csv(CACHE_PATH, parse_dates=["observation_date"], index_col="observation_date")
    logger.info("Loaded %s from cache (%d obs)", FRED_DEMAND_SERIES, len(df))
    return df.iloc[:, 0]


def _render_markdown(prophet_rep: dict, naive_rep: dict, meta: dict) -> str:
    p_overall = prophet_rep["overall"]
    n_overall = naive_rep["overall"]
    skill = 1.0 - (p_overall["wape"] / n_overall["wape"]) if n_overall["wape"] else 0.0
    verdict = (
        "Prophet beats the seasonal-naive baseline"
        if skill > 0
        else "Prophet does NOT beat the seasonal-naive baseline"
    )

    lines: List[str] = []
    lines.append("# Demand Forecast — Walk-Forward Backtest\n")
    lines.append(
        f"**Series:** FRED `{meta['series_id']}` "
        f"(Industrial Production: Semiconductors), monthly, "
        f"{meta['n_obs']} obs {meta['start']} → {meta['end']}.\n"
    )
    lines.append(
        f"**Method:** rolling-origin walk-forward — {meta['n_windows']} non-overlapping "
        f"origins, {meta['horizon']}-month horizon each. Models retrained at every origin.\n"
    )
    lines.append(
        f"**Baseline:** seasonal-naive (m={SEASONAL_PERIOD}). "
        "Prophet must beat this to justify its complexity.\n"
    )
    lines.append("## Headline\n")
    lines.append(f"- **Prophet WAPE:** {p_overall['wape']:.3f}  ·  MAPE {p_overall['mape']:.3f}  ·  RMSE {p_overall['rmse']:.2f}")
    lines.append(f"- **Seasonal-naive WAPE:** {n_overall['wape']:.3f}  ·  MAPE {n_overall['mape']:.3f}  ·  RMSE {n_overall['rmse']:.2f}")
    lines.append(f"- **Skill score (1 − WAPE_prophet/WAPE_naive):** {skill:+.1%}")
    lines.append(f"- **Verdict:** {verdict}.\n")

    lines.append("## Accuracy degradation by horizon (WAPE)\n")
    lines.append("| Horizon (months ahead) | Prophet WAPE | Naive WAPE | Prophet bias |")
    lines.append("|---:|---:|---:|---:|")
    for ph, nh in zip(prophet_rep["by_horizon"], naive_rep["by_horizon"]):
        lines.append(
            f"| {ph['horizon']} | {ph['wape']:.3f} | {nh['wape']:.3f} | {ph['bias']:+.2f} |"
        )
    lines.append("")
    lines.append("## Notes\n")
    lines.append(
        "- WAPE (Σ|a−f|/Σ|a|) is the headline metric; it does not blow up on low-volume "
        "months the way MAPE can.\n"
        "- `bias` is mean(forecast − actual): positive ⇒ systematic over-forecast.\n"
        "- Reproduce: `cd backend && python -m seeds.run_forecast_backtest`.\n"
    )
    return "\n".join(lines)


def main() -> None:
    series = _load_series()
    values = [float(v) for v in series.to_numpy()]

    from app.ml.backtest import walk_forward_backtest

    logger.info("Running Prophet backtest (%d windows × %d-month horizon)...", N_WINDOWS, HORIZON)
    prophet_rep = walk_forward_backtest(
        values, make_prophet_fit_predict(), horizon=HORIZON, n_windows=N_WINDOWS
    ).as_dict()

    logger.info("Running seasonal-naive baseline backtest...")
    naive_rep = walk_forward_backtest(
        values, seasonal_naive_fit_predict, horizon=HORIZON, n_windows=N_WINDOWS
    ).as_dict()

    meta = {
        "series_id": "IPG3344S",
        "n_obs": len(series),
        "start": str(series.index.min().date()),
        "end": str(series.index.max().date()),
        "horizon": HORIZON,
        "n_windows": N_WINDOWS,
    }

    docs_dir = REPO_ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    payload = {"meta": meta, "prophet": prophet_rep, "seasonal_naive": naive_rep}
    (docs_dir / "forecast_backtest.json").write_text(json.dumps(payload, indent=2))

    md = _render_markdown(prophet_rep, naive_rep, meta)
    (docs_dir / "FORECAST_BACKTEST.md").write_text(md)

    p_wape = prophet_rep["overall"]["wape"]
    n_wape = naive_rep["overall"]["wape"]
    skill = 1.0 - (p_wape / n_wape) if n_wape else 0.0
    logger.info(
        "DONE — Prophet WAPE=%.3f, naive WAPE=%.3f, skill=%+.1f%%. Wrote docs/FORECAST_BACKTEST.md",
        p_wape, n_wape, skill * 100,
    )


if __name__ == "__main__":
    main()
