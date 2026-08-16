"""
Walk-forward backtest of the demand forecaster on REAL data, vs a baseline.

Answers the question a forecasting reviewer actually asks: "does Prophet beat a
naive baseline on real semiconductor demand, and where does it degrade across
the horizon?" — not "what's one MAPE on one split?".

Source series: Census M3 `A34SNO` — Manufacturers' New Orders, Computers &
Electronic Products ($M, monthly, 1992->now) — the REAL macro *demand* target
(new orders = demand booked), loaded keyless at a PINNED ALFRED vintage committed
under seeds/data/a34sno_vintages/ — see the reproducibility note below. Three models
are run through the same rolling-origin harness:

  * prophet_seasonal   — Prophet with yearly seasonality (appropriate for monthly)
  * prophet_trend_only — Prophet with yearly_seasonality=False. HISTORICAL NOTE:
                         this arm existed to mirror the seasonality config the
                         retired per-part seed (seeds/train_forecasts.py) served,
                         so the backtest measured the config that actually shipped.
                         That seed is gone, so nothing "serves" this config any
                         more; the arm is kept as a seasonality ABLATION — it
                         answers "how much of Prophet's skill here is the yearly
                         term?" — and is labelled that way rather than as a
                         served-config row. The JSON key stays
                         `prophet_served_config` for artifact continuity.
  * seasonal-naive (m=12) — repeat the value from 12 months ago (the standard
                            cheap baseline Prophet must beat to justify itself)

Skill score = 1 - WAPE(prophet) / WAPE(naive). Positive ⇒ Prophet adds value.
Because both models are scored on identical actuals, WAPE_p/WAPE_n equals the
relative-MAE (MASE vs the out-of-sample seasonal-naive) — the scale-free read a
forecasting reviewer expects.

REPRODUCIBILITY — the series is VINTAGE-PINNED
----------------------------------------------
Census revises M3 in place and FRED mirrors the revision, so `A34SNO` is a moving
target. Until 2026-08-16 this script refetched it live on every run and OVERWROTE
`seeds/data/a34sno_monthly.csv` — a write-through cache, not a pin — so a published
number stopped reproducing the moment Census revised the series. It did: the
Prophet-vs-Chronos headline inverted. The series is now loaded at an explicit ALFRED
vintage via `seeds.macro_demand.load_demand_series`, the vintage and the input hashes
are recorded in every artifact, and nothing overwrites the cache unless a human passes
`--refresh-cache`. See `seeds/macro_demand.py` for the full account.

Usage:
    cd backend
    python -m seeds.run_forecast_backtest                    # uses the DEFAULT_VINTAGE pin
    python -m seeds.run_forecast_backtest --as-of 2026-08-16 # pin explicitly
    python -m seeds.run_forecast_backtest --offline          # committed bytes, no network
    python -m seeds.run_forecast_backtest --latest           # unpinned; flagged NOT reproducible

Writes docs/FORECAST_BACKTEST.md and docs/forecast_backtest.json (repo root).
"""
from __future__ import annotations

import argparse  # noqa: F401 — re-exported type for build_arg_parser's annotation
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from seeds.macro_demand import SeriesLoad

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from seeds.provenance import build_provenance, provenance_markdown  # noqa: E402

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


def make_prophet_fit_predict(yearly_seasonality: bool = True):
    """Build a Prophet-backed fit_predict callable (lazy import; quiet logging).

    `yearly_seasonality=False` gives the trend-only ablation arm. It originally
    mirrored the config the retired per-part seed served; that seed no longer
    exists, so the arm now measures only how much of Prophet's skill on this series
    comes from the yearly seasonal term. See the module docstring.
    """
    import pandas as pd
    from prophet import Prophet

    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    def fit_predict(train: Sequence[float]) -> List[float]:
        n = len(train)
        ds = pd.date_range(ANCHOR_DATE, periods=n, freq="MS")
        df = pd.DataFrame({"ds": ds, "y": list(train)})
        m = Prophet(
            yearly_seasonality=yearly_seasonality,
            weekly_seasonality=False,
            daily_seasonality=False,
            uncertainty_samples=0,   # point forecasts only — faster, bounds not needed here
        )
        m.fit(df)
        future = m.make_future_dataframe(periods=HORIZON, freq="MS", include_history=False)
        forecast = m.predict(future)
        return [float(v) for v in forecast["yhat"].tolist()]

    return fit_predict


def build_arg_parser(description: str) -> "argparse.ArgumentParser":
    """The vintage-pin CLI, shared with `seeds.run_chronos_benchmark`.

    Both scripts must score their models on the SAME bytes, so they take the same
    flags and resolve the series through the same loader.
    """
    import argparse

    from seeds.macro_demand import DEFAULT_VINTAGE

    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--as-of",
        default=DEFAULT_VINTAGE,
        metavar="YYYY-MM-DD",
        help=(
            "ALFRED data vintage to pin the series to (default: %(default)s). "
            "The series is loaded exactly as it stood on this date, so the backtest "
            "is reproducible even though Census revises M3 in place."
        ),
    )
    p.add_argument(
        "--latest",
        action="store_true",
        help=(
            "Use the latest FRED vintage instead of a pin. NOT REPRODUCIBLE — the "
            "artifact is flagged accordingly. Use only for exploration."
        ),
    )
    p.add_argument(
        "--refresh-pin",
        action="store_true",
        help="Re-download the pinned vintage from ALFRED and verify it still matches.",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Never touch the network; use committed bytes only.",
    )
    p.add_argument(
        "--no-real-time",
        action="store_true",
        help=(
            "Skip the per-origin real-time protocol. On by default: the pseudo "
            "real-time walk-forward is optimistic on a revised series."
        ),
    )
    p.add_argument(
        "--refresh-cache",
        action="store_true",
        help=(
            "Explicitly overwrite the legacy unpinned snapshot "
            "seeds/data/a34sno_monthly.csv from the loaded series. Off by default: "
            "the silent write-through of this file is what broke reproducibility."
        ),
    )
    return p


def _load_series(
    as_of: str | None = None,
    *,
    refresh_pin: bool = False,
    offline: bool = False,
    refresh_cache: bool = False,
) -> "SeriesLoad":  # noqa: F821 (seeds.macro_demand imported lazily)
    """Load the real A34SNO demand series AT A PINNED VINTAGE.

    Returns the full :class:`seeds.macro_demand.SeriesLoad` (values + vintage +
    hashes + reproducibility flag), not a bare Series, because every artifact this
    produces must record which bytes it was built from. See the module docstring of
    `seeds/macro_demand.py` for why the pin exists.
    """
    from seeds.macro_demand import CACHE_PATH, DEFAULT_VINTAGE, load_demand_series

    vintage = DEFAULT_VINTAGE if as_of is None else as_of
    load = load_demand_series(
        vintage, refresh_pin=refresh_pin, allow_network=not offline
    )
    logger.info(
        "Series %s: %d obs %s → %s | vintage=%s source=%s reproducible=%s values_sha256=%s",
        load.series.name, len(load.series), load.series.index.min().date(),
        load.series.index.max().date(), load.vintage, load.source,
        load.reproducible, load.values_sha256[:16],
    )
    for w in load.warnings:
        logger.warning(w)

    if refresh_cache:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        load.series.to_frame().to_csv(CACHE_PATH, index_label="observation_date")
        logger.warning(
            "--refresh-cache: OVERWROTE %s. Update COMMITTED_CACHE_SHA256 in "
            "seeds/macro_demand.py to match, or the offline fallback will report a "
            "hash mismatch.", CACHE_PATH,
        )
    return load


def run_real_time(reference_vintage: str | None) -> dict | None:
    """Score Prophet and the naive baseline under the TRUE real-time protocol.

    Each origin trains only on the ALFRED vintage that existed on its date, instead of
    slicing one fully revised series. Cheap (no Chronos, ~2 s) and generated rather than
    hand-quoted, so this doc cannot drift from the benchmark that shares the protocol.
    """
    from app.ml.backtest import backtest_folds
    from seeds.macro_demand import DEFAULT_VINTAGE, load_realtime_folds

    try:
        folds, rt_meta = load_realtime_folds(
            reference_vintage=reference_vintage or DEFAULT_VINTAGE, horizon=HORIZON
        )
    except Exception as exc:  # noqa: BLE001 - never fail the backtest over this
        logger.warning("real-time protocol unavailable: %s", exc)
        return None

    out: dict = {"meta": rt_meta, "models": {}}
    for name, fp in (
        ("prophet", make_prophet_fit_predict(yearly_seasonality=True)),
        ("seasonal_naive", seasonal_naive_fit_predict),
    ):
        logger.info("Real-time protocol: scoring %s...", name)
        out["models"][name] = backtest_folds(
            folds, fp, horizon=HORIZON, method="real_time_vintage_per_origin"
        ).as_dict()
    return out


def _render_real_time(real_time: dict | None, prophet_rep: dict, naive_rep: dict) -> List[str]:
    if not real_time:
        return []
    m = real_time["models"]
    lines: List[str] = ["## Real-time protocol — the number you could actually have achieved\n"]
    lines.append(
        "The headline above is *pseudo* real-time: it slices the latest, fully revised "
        "series, so every origin is shown observations that did not exist yet at that "
        "origin. Census revises this series in place, so that is real leakage. Below, each "
        "origin trains only on the ALFRED vintage that existed on its date — same training "
        "lengths, same target months, same actuals, so the gap is data revision alone.\n"
    )
    lines.append("| Model | Real-time WAPE | Pseudo real-time WAPE | Revised data flatters by |")
    lines.append("|---|---:|---:|---:|")
    for key, label, pseudo in (
        ("prophet", "**Prophet** (seasonal)", prophet_rep),
        ("seasonal_naive", f"Seasonal-naive (m={SEASONAL_PERIOD})", naive_rep),
    ):
        rt_w = m[key]["overall"]["wape"]
        ps_w = pseudo["overall"]["wape"]
        lines.append(
            f"| {label} | **{rt_w:.4f}** | {ps_w:.4f} | "
            f"{((rt_w - ps_w) / rt_w * 100 if rt_w else 0.0):+.1f}% |"
        )
    lines.append("")
    rt_skill = (
        1.0 - m["prophet"]["overall"]["wape"] / m["seasonal_naive"]["overall"]["wape"]
        if m["seasonal_naive"]["overall"]["wape"] else 0.0
    )
    lines.append(
        f"Prophet's skill score against the naive baseline under the real-time protocol is "
        f"**{rt_skill:+.1%}** (vs "
        f"{1.0 - prophet_rep['overall']['wape'] / naive_rep['overall']['wape']:+.1%} on revised "
        "data). Prophet still beats the baseline — but every absolute WAPE quoted above the "
        "fold is optimistic. The three-model version of this table, including Chronos, is in "
        "[CHRONOS_BENCHMARK.md](CHRONOS_BENCHMARK.md).\n"
    )
    return lines


def _vintage_block(meta: dict) -> str:
    """The reproducibility disclosure every artifact built from this series carries."""
    lines: List[str] = []
    vintage = meta.get("vintage")
    if vintage:
        lines.append(
            f"**Data vintage (pinned):** `{vintage}` — the series exactly as it stood "
            f"on that date, served by ALFRED and committed at "
            f"`{meta.get('vintage_file')}`.\n"
        )
        lines.append(
            f"**Input hash:** file sha256 `{(meta.get('vintage_file_sha256') or '')[:16]}…` · "
            f"observation-values sha256 `{(meta.get('series_values_sha256') or '')[:16]}…`. "
            f"Loaded via `{meta.get('vintage_source')}`.\n"
        )
        lines.append(
            "**Why a pin:** Census revises M3 *in place* and FRED mirrors the revision, "
            "so an unpinned re-run of this backtest silently scores a different series. "
            "That is not hypothetical — it inverted this repo's Prophet-vs-Chronos "
            "headline (quantified in the vintage-sensitivity table of "
            "[CHRONOS_BENCHMARK.md](CHRONOS_BENCHMARK.md)). Re-running with the same "
            "`--as-of` reproduces the numbers below exactly.\n"
        )
    else:
        lines.append(
            "> ⚠️ **UNPINNED RUN — NOT REPRODUCIBLE.** This artifact was built from the "
            "latest FRED vintage rather than a pinned one. Census revises this series in "
            "place, so these numbers will not reproduce on a later date. Re-run with "
            "`--as-of YYYY-MM-DD` before quoting anything from here.\n"
        )
    for w in meta.get("warnings") or []:
        lines.append(f"> ⚠️ {w}\n")
    return "\n".join(lines)


def _render_markdown(prophet_rep: dict, naive_rep: dict, meta: dict, prophet_served_rep: dict | None = None, real_time: dict | None = None) -> str:
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
        "<!-- GENERATED FILE — do not hand-edit. "
        "Regenerate: `cd backend && python -m seeds.run_forecast_backtest` -->\n"
    )
    lines.append(
        f"**Series:** Census M3 / FRED `{meta['series_id']}` "
        f"(Manufacturers' New Orders: Computers & Electronic Products, $M), monthly, "
        f"{meta['n_obs']} obs {meta['start']} → {meta['end']}.\n"
    )
    lines.append(_vintage_block(meta))
    lines.append(
        f"**Method:** rolling-origin walk-forward — {meta['n_windows']} non-overlapping "
        f"origins, {meta['horizon']}-month horizon each. Models retrained at every origin.\n"
    )
    lines.append(
        f"**Baseline:** seasonal-naive (m={SEASONAL_PERIOD}). "
        "Prophet must beat this to justify its complexity.\n"
    )
    lines.append(
        "**Scope — read this before quoting a number from here.** This is an *aggregate "
        "industry* series: one national monthly total, not per-part demand. It says "
        "nothing about how well any individual component can be forecast, and there is no "
        "per-part demand model in this app (the synthetic one was retired — see "
        "`docs/INTERMITTENT_DEMAND.md`). Per-SKU demand evidence lives there instead, on "
        "the Monash car-parts panel. With 3 origins this series also cannot support a "
        "significance test; that is why none is reported below.\n"
    )
    lines.append("## Headline\n")
    lines.append(f"- **Prophet (seasonal) WAPE:** {p_overall['wape']:.4f}  ·  MAPE {p_overall['mape']:.4f}  ·  RMSE {p_overall['rmse']:.2f}")
    if prophet_served_rep is not None:
        s_overall = prophet_served_rep["overall"]
        s_skill = 1.0 - (s_overall["wape"] / n_overall["wape"]) if n_overall["wape"] else 0.0
        lines.append(
            f"- **Prophet (trend-only ablation, no yearly term) WAPE:** {s_overall['wape']:.4f}  ·  "
            f"MAPE {s_overall['mape']:.4f}  ·  RMSE {s_overall['rmse']:.2f}  ·  skill {s_skill:+.1%}"
        )
    lines.append(f"- **Seasonal-naive WAPE:** {n_overall['wape']:.4f}  ·  MAPE {n_overall['mape']:.4f}  ·  RMSE {n_overall['rmse']:.2f}")
    lines.append(f"- **Skill score (1 − WAPE_prophet/WAPE_naive):** {skill:+.1%}")
    lines.append(f"- **Verdict:** {verdict}.\n")

    lines.extend(_render_real_time(real_time, prophet_rep, naive_rep))

    lines.append("## Accuracy degradation by horizon (WAPE)\n")
    lines.append("| Horizon (months ahead) | Prophet WAPE | Naive WAPE | Prophet bias |")
    lines.append("|---:|---:|---:|---:|")
    for ph, nh in zip(prophet_rep["by_horizon"], naive_rep["by_horizon"], strict=True):
        lines.append(
            f"| {ph['horizon']} | {ph['wape']:.3f} | {nh['wape']:.3f} | {ph['bias']:+.2f} |"
        )
    lines.append("")
    lines.append("## Notes\n")
    lines.append(
        "- WAPE (Σ|a−f|/Σ|a|) is the headline metric; it does not blow up on low-volume "
        "months the way MAPE can.\n"
        "- `bias` is mean(forecast − actual): positive ⇒ systematic over-forecast.\n"
        f"- Reproduce exactly: `cd backend && python -m seeds.run_forecast_backtest "
        f"--as-of {meta.get('vintage', 'YYYY-MM-DD')}`. The vintage flag is what makes "
        "\"exactly\" true.\n"
    )
    lines.append(provenance_markdown(meta.get("provenance", {})))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    args = build_arg_parser(
        "Walk-forward backtest of Prophet vs a seasonal-naive baseline on a "
        "vintage-pinned Census M3 demand series."
    ).parse_args(argv)

    load = _load_series(
        None if args.latest else args.as_of,
        refresh_pin=args.refresh_pin,
        offline=args.offline,
        refresh_cache=args.refresh_cache,
    )
    series = load.series
    values = [float(v) for v in series.to_numpy()]

    from app.ml.backtest import walk_forward_backtest

    logger.info("Running Prophet (seasonal) backtest (%d windows × %d-month horizon)...", N_WINDOWS, HORIZON)
    prophet_rep = walk_forward_backtest(
        values, make_prophet_fit_predict(yearly_seasonality=True), horizon=HORIZON, n_windows=N_WINDOWS
    ).as_dict()

    logger.info("Running Prophet (served config: trend-only) backtest...")
    prophet_served_rep = walk_forward_backtest(
        values, make_prophet_fit_predict(yearly_seasonality=False), horizon=HORIZON, n_windows=N_WINDOWS
    ).as_dict()

    logger.info("Running seasonal-naive baseline backtest...")
    naive_rep = walk_forward_backtest(
        values, seasonal_naive_fit_predict, horizon=HORIZON, n_windows=N_WINDOWS
    ).as_dict()

    meta = dict(load.meta())
    meta.update({"horizon": HORIZON, "n_windows": N_WINDOWS})
    meta["provenance"] = build_provenance(
        generator="seeds.run_forecast_backtest",
        inputs={"demand_series": load.path} if load.path else {},
        extra={
            "vintage": load.vintage,
            "series_values_sha256": load.values_sha256,
            "reproducible": load.reproducible,
        },
    )

    real_time = None if args.no_real_time else run_real_time(load.vintage)

    docs_dir = REPO_ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "meta": meta,
        # The key names read backwards and have burned a transcription before, so the
        # mapping is stated IN the artifact rather than only in this module's docstring:
        # `prophet` is the SEASONAL arm (the headline), `prophet_served_config` is the
        # TREND-ONLY ablation. The latter key is historical — nothing "serves" that
        # config any more — and is kept only so older artifacts stay comparable.
        "arms": {
            "prophet": "Prophet, yearly_seasonality=True — the headline arm",
            "prophet_served_config": (
                "Prophet, yearly_seasonality=False — seasonality ABLATION. Legacy key "
                "name: no served config corresponds to it any more."
            ),
            "seasonal_naive": f"Repeat the value from m={SEASONAL_PERIOD} months ago — baseline",
        },
        "prophet": prophet_rep,
        "prophet_served_config": prophet_served_rep,
        "seasonal_naive": naive_rep,
        "real_time": real_time,
    }
    (docs_dir / "forecast_backtest.json").write_text(json.dumps(payload, indent=2))

    md = _render_markdown(prophet_rep, naive_rep, meta, prophet_served_rep, real_time)
    (docs_dir / "FORECAST_BACKTEST.md").write_text(md)

    p_wape = prophet_rep["overall"]["wape"]
    n_wape = naive_rep["overall"]["wape"]
    skill = 1.0 - (p_wape / n_wape) if n_wape else 0.0
    logger.info(
        "DONE — Prophet WAPE=%.3f, naive WAPE=%.3f, skill=%+.1f%%. Wrote docs/FORECAST_BACKTEST.md",
        p_wape, n_wape, skill * 100,
    )

    # MLflow experiment tracking + registry (P5). Logs the REAL backtest metrics
    # (WAPE/RMSE/bias) and the Prophet seasonality config, then registers the
    # lowest-RMSE forecast run as champion. Best-effort — never fails the backtest.
    import os
    if os.environ.get("DISABLE_MLFLOW") != "1":
        try:
            _log_prophet_to_mlflow(values, prophet_rep, naive_rep, meta, skill)
        except Exception as exc:  # noqa: BLE001 - tracking is non-critical
            logger.warning("MLflow tracking skipped (%s)", exc)


def _log_prophet_to_mlflow(values, prophet_rep, naive_rep, meta, skill) -> None:
    """Fit a Prophet model on the full real series and log the backtest run."""
    from app.ml.mlflow_tracking import log_prophet_backtest

    p_overall = prophet_rep["overall"]
    params = {
        "model": "prophet",
        "yearly_seasonality": True,
        "weekly_seasonality": False,
        "daily_seasonality": False,
        "uncertainty_samples": 0,
        "horizon": meta["horizon"],
        "n_windows": meta["n_windows"],
        "seasonal_period": SEASONAL_PERIOD,
        "series_id": meta["series_id"],
        "n_obs": meta["n_obs"],
        "data_vintage": meta.get("vintage"),
        "series_values_sha256": meta.get("series_values_sha256"),
        "backtest_method": "walk_forward_rolling_origin",
    }
    metrics = {
        "wape": p_overall["wape"],
        "mape": p_overall["mape"],
        "rmse": p_overall["rmse"],
        "bias": p_overall["bias"],
        "tracking_signal": p_overall["tracking_signal"],
        "naive_wape": naive_rep["overall"]["wape"],
        "naive_rmse": naive_rep["overall"]["rmse"],
        "skill_score": skill,
    }

    # Fit one Prophet on the entire real series for the registry artifact (same
    # config as the backtest folds).
    model = None
    try:
        import pandas as pd
        from prophet import Prophet

        ds = pd.date_range(ANCHOR_DATE, periods=len(values), freq="MS")
        df = pd.DataFrame({"ds": ds, "y": list(values)})
        m = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            uncertainty_samples=0,
        )
        m.fit(df)
        model = m
    except Exception as exc:  # pragma: no cover - artifact fit best-effort
        logger.warning("could not fit full-series Prophet for artifact: %s", exc)

    out = log_prophet_backtest(params=params, metrics=metrics, model=model)
    champ = out.get("champion")
    if champ:
        logger.info(
            "MLflow champion: %s (RMSE=%.2f) registered as %s v%s [alias=%s]",
            champ["model_name"] or "prophet", champ["value"],
            champ["registered_model"], champ["version"], champ["alias"],
        )


if __name__ == "__main__":
    main()
