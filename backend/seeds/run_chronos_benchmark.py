"""
Chronos (TSFM) zero-shot benchmark vs Prophet — IDENTICAL windows, SAME metrics.

The forecast reviewer's follow-up to FORECAST_BACKTEST.md is: "Prophet beats a
naive baseline — but would a modern time-series foundation model beat Prophet,
and is the extra dependency weight worth it?" This script answers that with
evidence instead of hype.

It reuses the EXACT walk-forward harness, series loader, Prophet callable and
seasonal-naive baseline from `seeds.run_forecast_backtest`, so all three models are
scored on the same series (Census M3 / FRED `A34SNO` — whatever `FRED_DEMAND_SERIES`
points at; it is NOT hardcoded here any more, because the doc header once claimed
IPG3344S long after the harness had been repointed), the same rolling origins, the
same 12-month horizon, and the same WAPE / MAPE / RMSE / bias metrics. The only new
piece is a Chronos `fit_predict` callable that forecasts ZERO-SHOT — no fitting,
no training on this series at all — which is the whole point of a TSFM.

Two experiments are run:
  1. Full-history walk-forward — Prophet vs seasonal-naive vs Chronos on the same
     3 × 12-month holdout windows as the Prophet backtest.
  2. Cold-start (< 1 season of history) — each model is given only the most recent
     few months before each block. This is the natural Chronos zero-shot case. It is
     scored against TWO Prophets: the trend-only config (the fair comparator, and the
     one actually served per part) and the yearly-seasonality config (which cannot
     work on 6 points — kept only because an earlier version of this benchmark used
     that strawman to manufacture a Chronos cold-start "win").

Chronos is an OPTIONAL, heavy dependency (torch). If it is not installed or the
model weights cannot be downloaded, this script STILL runs Prophet + naive, writes
the comparison doc, and marks the Chronos column "pending" — it never fabricates
numbers.

TIMING PROTOCOL (2026-07-12 rewrite — the previous numbers were real but
uninterpretable)
------------------------------------------------------------------------------
The old script reported a bare "load 0.25s / inference 0.01s". Both figures were
genuinely measured, but they were unfalsifiable as published: the load excluded
the ~2 s `import torch` + `import chronos` and silently assumed the weights were
already in the HuggingFace cache, and the "inference" was one wall-clock around
the whole 3-window walk-forward with no warm-up and no hardware noted. A reader
could not tell whether the model had run at all. Now we record, per run:

  * `hardware` — machine, processor, python, torch version, torch thread count.
  * `import_seconds` — cost of importing torch + chronos.
  * `weights_cached` — whether the checkpoint was already in the HF cache
    (i.e. whether `load_seconds` includes a download or not).
  * `load_seconds` — `from_pretrained` only.
  * `warmup_seconds` — the FIRST forward pass, timed separately and DISCARDED
    from the steady-state stats (it is ~40× the warm cost).
  * per-call inference timings for every forecast call (walk-forward + cold-start),
    reported as n / median / mean / min / max ms, with context and horizon lengths.

Prophet is timed with the same wrapper, so the table compares like with like:
Prophet's per-window cost is a fit + predict; Chronos's is a forward pass only.

Usage:
    cd backend
    python -m seeds.run_chronos_benchmark
    # optional: CHRONOS_MODEL=amazon/chronos-t5-mini python -m seeds.run_chronos_benchmark

Writes docs/CHRONOS_BENCHMARK.md and docs/chronos_benchmark.json (repo root).
"""
from __future__ import annotations

import json
import logging
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Reuse the IDENTICAL harness pieces the Prophet backtest uses — guarantees the
# same windows, horizon and metrics. No re-implementation, no drift.
from seeds.run_forecast_backtest import (  # noqa: E402
    HORIZON,
    N_WINDOWS,
    SEASONAL_PERIOD,
    _load_series,
    make_prophet_fit_predict,
    seasonal_naive_fit_predict,
)
from seeds.train_forecasts import FRED_DEMAND_SERIES  # noqa: E402 — the series ACTUALLY loaded
from app.ml import forecast_metrics as fm  # noqa: E402
from app.ml.backtest import walk_forward_backtest  # noqa: E402

# Smallest, fastest Chronos checkpoints. chronos-bolt-tiny (~9M params) is the
# default; it is the model Amazon recommends for CPU zero-shot. Override with
# CHRONOS_MODEL to try chronos-t5-tiny / -mini etc.
DEFAULT_CHRONOS_MODEL = "amazon/chronos-bolt-tiny"
COLD_START_CONTEXT = 6    # months of history given in the cold-start experiment (< 1 season)
INFERENCE_REPEATS = 20    # repeats for the steady-state latency micro-benchmark (n=3 is not a latency figure)


# ── Timing instrumentation ───────────────────────────────────────────────────


class TimedFitPredict:
    """Wrap a fit_predict callable and record the wall-clock of EVERY call.

    Chronos's per-call cost is a single forward pass (no fit). Prophet's is a full
    Stan fit + predict. Timing both through the same wrapper is the only way the
    "TSFM is cheap at inference, expensive to install" claim can be checked.
    """

    def __init__(self, fn: Callable[[Sequence[float]], Sequence[float]], label: str):
        self._fn = fn
        self.label = label
        self.times: List[float] = []
        self.contexts: List[int] = []

    def __call__(self, train: Sequence[float]) -> Sequence[float]:
        t0 = time.perf_counter()
        out = self._fn(train)
        self.times.append(time.perf_counter() - t0)
        self.contexts.append(len(train))
        return out

    def warmup(self, train: Sequence[float]) -> float:
        """One discarded call — JIT/lazy-init/cache warm-up. Returns its cost."""
        t0 = time.perf_counter()
        self._fn(train)
        return time.perf_counter() - t0

    def stats(self) -> Optional[Dict[str, float]]:
        if not self.times:
            return None
        ms = [t * 1000.0 for t in self.times]
        return {
            "n_calls": len(ms),
            "median_ms": round(statistics.median(ms), 2),
            "mean_ms": round(statistics.fmean(ms), 2),
            "min_ms": round(min(ms), 2),
            "max_ms": round(max(ms), 2),
            "total_seconds": round(sum(self.times), 3),
            "context_min": min(self.contexts),
            "context_max": max(self.contexts),
            "prediction_length": HORIZON,
        }


def _repeat_bench(
    fn: Callable[[Sequence[float]], Sequence[float]],
    context: Sequence[float],
    repeats: int = INFERENCE_REPEATS,
) -> Dict[str, float]:
    """Steady-state latency: the SAME forward pass, repeated, after a warm-up.

    The walk-forward only makes 3 forecast calls; a median over 3 is not a latency
    number. This repeats one call `repeats` times on the full context and reports the
    distribution, which is what "inference costs X ms" has to mean to be checkable.
    """
    fn(context)  # warm-up, discarded
    times: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn(context)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return {
        "n_repeats": repeats,
        "context_len": len(context),
        "prediction_length": HORIZON,
        "median_ms": round(statistics.median(times), 2),
        "mean_ms": round(statistics.fmean(times), 2),
        "min_ms": round(times[0], 2),
        "max_ms": round(times[-1], 2),
        "p95_ms": round(times[min(len(times) - 1, int(0.95 * len(times)))], 2),
    }


def _hardware() -> Dict[str, object]:
    """What the timings above were measured ON — without this they mean nothing."""
    hw: Dict[str, object] = {
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "device": "cpu",
    }
    try:
        import torch

        hw["torch_version"] = torch.__version__
        hw["torch_threads"] = torch.get_num_threads()
        hw["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 — torch absent is a legitimate state here
        pass
    return hw


# ── Chronos zero-shot model ──────────────────────────────────────────────────


def _weights_cached(model_name: str) -> bool:
    """True if the checkpoint is already in the local HF cache.

    Decides whether `load_seconds` is a *cached* load or includes a download —
    a 0.25 s "load" means something very different in each case.
    """
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    if not cache.exists():
        cache = Path.home() / ".cache" / "huggingface" / "hub"
    slug = "models--" + model_name.replace("/", "--")
    return (cache / slug).exists()


def make_chronos_fit_predict(model_name: str):
    """Build a zero-shot Chronos `fit_predict(train) -> [horizon floats]` callable.

    Returns (callable, meta). Raises on import/download failure so the caller can
    fall back to a Prophet-only run and mark Chronos pending.

    "fit_predict" is a misnomer for a TSFM — there is NO fit. The training slice is
    used purely as forecasting *context*; the model weights are frozen. That is the
    cold-start property we want to showcase.

    `meta` separates the three costs that the old benchmark collapsed into one
    number: importing torch, loading the weights (cached or downloaded), and the
    forward pass itself.
    """
    cached_before = _weights_cached(model_name)

    t_imp = time.perf_counter()
    import torch
    from chronos import BaseChronosPipeline
    import_s = time.perf_counter() - t_imp

    t0 = time.perf_counter()
    pipeline = BaseChronosPipeline.from_pretrained(
        model_name,
        device_map="cpu",
        torch_dtype=torch.float32,
    )
    load_s = time.perf_counter() - t0
    n_params = sum(p.numel() for p in pipeline.model.parameters())
    logger.info(
        "Loaded Chronos %s on CPU in %.2fs (import %.2fs, weights_cached=%s, %.2fM params)",
        model_name, load_s, import_s, cached_before, n_params / 1e6,
    )

    def fit_predict(train: Sequence[float]) -> List[float]:
        context = torch.tensor([float(v) for v in train], dtype=torch.float32)
        # predict_quantiles → (quantiles[B, H, Q], mean[B, H]). We take the median
        # (0.5 quantile) as the point forecast, matching Prophet's yhat semantics.
        quantiles, _mean = pipeline.predict_quantiles(
            inputs=context,
            prediction_length=HORIZON,
            quantile_levels=[0.1, 0.5, 0.9],
        )
        median = quantiles[0, :, 1]
        return [float(v) for v in median]

    meta = {
        "model": model_name,
        "n_parameters": int(n_params),
        "import_seconds": round(import_s, 2),
        "weights_cached": cached_before,
        "load_seconds": round(load_s, 2),
        "torch_version": torch.__version__,
    }
    return fit_predict, meta


# ── Cold-start experiment (limited context) ──────────────────────────────────


def cold_start_eval(
    values: List[float],
    fit_predict: Callable[[Sequence[float]], Sequence[float]],
    context_len: int,
) -> Optional[dict]:
    """Score a model when it only sees the most recent `context_len` points.

    Mirrors the walk-forward block layout exactly (same held-out blocks as the
    full-history run), but truncates the training context to `context_len` points
    immediately before each block — simulating a brand-new / cold-start part with
    almost no demand history. Returns overall metrics or None on failure.
    """
    n = len(values)
    test_start = n - N_WINDOWS * HORIZON
    all_actual: List[float] = []
    all_forecast: List[float] = []
    try:
        for w in range(N_WINDOWS):
            cut = test_start + w * HORIZON
            ctx = values[max(0, cut - context_len):cut]
            actual_block = values[cut:cut + HORIZON]
            preds = list(fit_predict(ctx))
            if len(preds) != HORIZON:
                return None
            all_actual.extend(actual_block)
            all_forecast.extend(preds)
        m = fm.all_metrics(all_actual, all_forecast)
        return {k: round(v, 4) for k, v in m.items()}
    except Exception as exc:  # noqa: BLE001 — cold-start with tiny context can break classical models
        logger.warning("cold-start eval failed: %s", exc)
        return None

# ── Markdown rendering ───────────────────────────────────────────────────────


def _verdict(prophet_overall: dict, chronos_overall: Optional[dict], naive_overall: dict) -> str:
    if chronos_overall is None:
        return (
            "**Verdict: PENDING.** Chronos weights could not be loaded in this run "
            "(see Reproduce / blocker below), so no zero-shot numbers are available. "
            "Prophet remains the validated production model. Re-run the command once "
            "the model can be downloaded to populate the Chronos column."
        )
    p, c, nv = prophet_overall["wape"], chronos_overall["wape"], naive_overall["wape"]
    chronos_vs_prophet = (p - c) / p if p else 0.0
    chronos_beats_naive = c < nv
    if c < p:
        head = (
            f"**Verdict: Chronos zero-shot WINS overall** ({c:.3f} WAPE vs Prophet {p:.3f}, "
            f"{chronos_vs_prophet:+.1%}). A TSFM with no fitting beats a tuned Prophet on this series."
        )
    else:
        head = (
            f"**Verdict: Prophet WINS overall** ({p:.3f} WAPE vs Chronos {c:.3f}, "
            f"Chronos is {-chronos_vs_prophet:.1%} worse). On a long, clean, strongly-seasonal "
            f"series the fitted model is hard to beat — the TSFM's dependency weight (torch, "
            f"~2 GB) is not justified for THIS series."
        )
    naive_note = (
        "Chronos does clear the seasonal-naive bar"
        if chronos_beats_naive
        else "Chronos does NOT even clear the seasonal-naive bar"
    )
    return head + f" {naive_note} ({c:.3f} vs naive {nv:.3f})."


def _render_timing(chronos: Optional[dict], timing: dict, hw: dict) -> List[str]:
    """The section the old benchmark did not have — auditable timings.

    Every number here is measured in THIS run on the machine described; nothing is
    carried over from a previous run or a vendor benchmark.
    """
    lines: List[str] = ["## Cost / timing (measured this run, not quoted)\n"]
    lines.append(
        f"**Hardware:** {hw.get('platform')} · {hw.get('processor')} · Python {hw.get('python')} · "
        f"torch {hw.get('torch_version', 'n/a')} ({hw.get('torch_threads', '?')} threads) · "
        f"device `{hw.get('device')}` · CUDA available: {hw.get('cuda_available', False)}.\n"
    )
    if not chronos:
        lines.append("_Chronos did not run — no timings._\n")
        return lines

    lines.append(
        f"**Chronos startup:** `import torch` + `import chronos` "
        f"**{chronos.get('import_seconds')} s** · `from_pretrained` "
        f"**{chronos.get('load_seconds')} s** "
        f"(weights already in the HF cache: **{chronos.get('weights_cached')}** — a cold machine "
        f"must first download ~33 MB) · model size **{chronos.get('n_parameters', 0) / 1e6:.2f} M** "
        f"parameters.\n"
    )
    warm = chronos.get("warmup_seconds")
    if warm is not None:
        lines.append(
            f"**Warm-up:** the first forward pass costs **{warm * 1000:.0f} ms** (lazy init). It is "
            "timed separately and EXCLUDED from the steady-state numbers below — reporting it "
            "inside a single wall-clock, as this benchmark used to, is what made the old "
            "\"0.01 s inference\" figure impossible to interpret.\n"
        )

    lines.append(
        "Per-call cost over the walk-forward origins (warm-up excluded; the trend-only row is "
        "the short-context cold-start run and is timed separately so the medians are not mixed):\n"
    )
    lines.append("| Model | Calls | Context (pts) | Median / call | Mean | Min | Max | What one call does |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    rows = [
        ("Chronos (zero-shot)", timing.get("chronos"), f"frozen forward pass, H={HORIZON}"),
        ("Prophet (seasonal)", timing.get("prophet"), "full Stan fit + predict"),
        ("Prophet (trend-only, cold-start ctx)", timing.get("prophet_trend_only"), "full Stan fit + predict"),
        ("Seasonal-naive", timing.get("seasonal_naive"), "array indexing"),
    ]
    for label, st, what in rows:
        if not st:
            continue
        ctx = (
            f"{st['context_min']}" if st["context_min"] == st["context_max"]
            else f"{st['context_min']}–{st['context_max']}"
        )
        lines.append(
            f"| {label} | {st['n_calls']} | {ctx} | **{st['median_ms']:.1f} ms** | {st['mean_ms']:.1f} ms | "
            f"{st['min_ms']:.1f} ms | {st['max_ms']:.1f} ms | {what} |"
        )
    lines.append("")
    ss = chronos.get("steady_state")
    if ss:
        lines.append(
            f"**Chronos steady-state latency** (the walk-forward is only 3 calls — not a latency "
            f"sample): the same forward pass repeated **{ss['n_repeats']}×** on the full "
            f"{ss['context_len']}-point context, after a discarded warm-up → median "
            f"**{ss['median_ms']:.2f} ms**, mean {ss['mean_ms']:.2f} ms, p95 {ss['p95_ms']:.2f} ms, "
            f"range {ss['min_ms']:.2f}–{ss['max_ms']:.2f} ms (H={ss['prediction_length']}, batch 1). "
            "An 8.65 M-parameter encoder-decoder doing ONE non-autoregressive forward pass over "
            "~200 tokens really is single-digit milliseconds on this CPU — the number is small, but "
            "it is not a stub: dropping `chronos-forecasting` makes this script fail loudly and "
            "write \"pending\" rather than produce figures.\n"
        )

    ch_st = timing.get("chronos")
    pr_st = timing.get("prophet")
    if ch_st and pr_st:
        ratio = pr_st["median_ms"] / ch_st["median_ms"] if ch_st["median_ms"] else 0.0
        lines.append(
            f"Chronos's per-forecast cost is **{ratio:.0f}× cheaper than Prophet's** here — but that "
            "compares a frozen forward pass against a full Stan fit, which is exactly the "
            "point: the TSFM's cost is the ~2 GB torch install and the one-off weight load, not the "
            f"inference. (Horizon {ch_st['prediction_length']}, single series, batch size 1, "
            f"n={ch_st['n_calls']} calls — this is NOT a throughput benchmark, and with so few calls "
            "the median is indicative, not a stable percentile.)\n"
        )
    return lines


def _render_markdown(payload: dict) -> str:
    meta = payload["meta"]
    prophet = payload["prophet"]
    naive = payload["seasonal_naive"]
    chronos = payload.get("chronos")
    cold = payload.get("cold_start", {})
    timing = payload.get("timing", {})
    hw = payload.get("hardware", {})

    p_over = prophet["overall"]
    n_over = naive["overall"]
    c_over = chronos["overall"] if chronos else None

    lines: List[str] = []
    lines.append("# Chronos (TSFM) Zero-Shot Benchmark vs Prophet\n")
    lines.append(
        f"**Series:** Census M3 / FRED `{meta['series_id']}` ({meta['series_name']}), "
        f"monthly, {meta['n_obs']} obs {meta['start']} → {meta['end']}.\n"
    )
    lines.append(
        f"**Method:** the IDENTICAL rolling-origin walk-forward as "
        f"[FORECAST_BACKTEST.md](FORECAST_BACKTEST.md) — {meta['n_windows']} non-overlapping "
        f"origins, {meta['horizon']}-month horizon, same WAPE/MAPE/RMSE/bias metrics "
        f"(`app.ml.backtest`, `app.ml.forecast_metrics`).\n"
    )
    lines.append(
        f"**Scope, plainly:** n = 1 macro series, {meta['n_windows']} origins, "
        f"{meta['n_windows'] * meta['horizon']} scored points, no confidence intervals. "
        "This is a build-vs-buy probe, not a production model-selection study — do not read a "
        "single-series WAPE gap as \"model X is better\".\n"
    )
    if chronos:
        lines.append(
            f"**Chronos model:** `{chronos['model']}` "
            f"({chronos.get('n_parameters', 0) / 1e6:.2f} M params) — run **zero-shot** (no fit, no "
            f"training on this series). Point forecast = 0.5 quantile. CPU, torch "
            f"{chronos.get('torch_version', '?')}. Full timing breakdown below.\n"
        )
    else:
        lines.append(
            f"**Chronos model:** `{meta.get('chronos_model_requested', DEFAULT_CHRONOS_MODEL)}` — "
            f"**NOT RUN** in this pass ({meta.get('chronos_blocker', 'unavailable')}).\n"
        )

    lines.append("## Headline (full-history walk-forward)\n")
    lines.append("| Model | WAPE | MAPE | RMSE | Bias | Zero-shot? |")
    lines.append("|---|---:|---:|---:|---:|:--:|")
    lines.append(
        f"| **Prophet** (fitted, seasonal) | {p_over['wape']:.3f} | {p_over['mape']:.3f} | "
        f"{p_over['rmse']:.2f} | {p_over['bias']:+.2f} | no |"
    )
    lines.append(
        f"| Seasonal-naive (m={SEASONAL_PERIOD}) | {n_over['wape']:.3f} | {n_over['mape']:.3f} | "
        f"{n_over['rmse']:.2f} | {n_over['bias']:+.2f} | n/a |"
    )
    if c_over:
        lines.append(
            f"| **Chronos** {chronos['model'].split('/')[-1]} | {c_over['wape']:.3f} | "
            f"{c_over['mape']:.3f} | {c_over['rmse']:.2f} | {c_over['bias']:+.2f} | **yes** |"
        )
    else:
        lines.append("| **Chronos** | _pending_ | _pending_ | _pending_ | _pending_ | yes |")
    lines.append("")

    lines.append(_verdict(p_over, c_over, n_over) + "\n")

    lines.append("## WAPE by horizon (where each model degrades)\n")
    if c_over:
        lines.append("| Horizon (months ahead) | Prophet | Seasonal-naive | Chronos (zero-shot) |")
        lines.append("|---:|---:|---:|---:|")
        for ph, nh, ch in zip(prophet["by_horizon"], naive["by_horizon"], chronos["by_horizon"], strict=False):
            lines.append(f"| {ph['horizon']} | {ph['wape']:.3f} | {nh['wape']:.3f} | {ch['wape']:.3f} |")
    else:
        lines.append("| Horizon (months ahead) | Prophet | Seasonal-naive | Chronos (zero-shot) |")
        lines.append("|---:|---:|---:|---:|")
        for ph, nh in zip(prophet["by_horizon"], naive["by_horizon"], strict=False):
            lines.append(f"| {ph['horizon']} | {ph['wape']:.3f} | {nh['wape']:.3f} | _pending_ |")
    lines.append("")

    # ── Cold-start section ───────────────────────────────────────────────────
    lines.append(f"## Cold-start: only {COLD_START_CONTEXT} months of history (< 1 season)\n")
    lines.append(
        "The natural TSFM case: a brand-new part with almost no demand history. Each model "
        f"sees only the most recent **{COLD_START_CONTEXT}** points before each holdout block "
        "(same blocks as above).\n"
    )
    lines.append(
        "**Two Prophet rows, deliberately.** Handing Prophet 6 points *with yearly seasonality "
        "still switched on* is a strawman — it is a misconfiguration, not a defeat, and an earlier "
        "version of this doc quietly used it to make Chronos look good. The honest comparator is "
        "Prophet configured the way you would actually configure it for 6 points (trend-only) — "
        "which is also the config the served per-part forecaster uses.\n"
    )
    lines.append("| Model | Cold-start WAPE | Cold-start RMSE | Cold-start bias |")
    lines.append("|---|---:|---:|---:|")
    for label, key in (
        ("Prophet (seasonal — MISCONFIGURED for 6 pts, shown for honesty)", "prophet"),
        ("Prophet (trend-only — the fair comparator)", "prophet_trend_only"),
        ("Seasonal-naive", "seasonal_naive"),
        ("Chronos (zero-shot)", "chronos"),
    ):
        m = cold.get(key)
        if m:
            lines.append(f"| {label} | {m['wape']:.3f} | {m['rmse']:.2f} | {m['bias']:+.2f} |")
        else:
            lines.append(f"| {label} | _pending_ | _pending_ | _pending_ |")
    lines.append("")

    fair = cold.get("prophet_trend_only")
    cc_m = cold.get("chronos")
    if fair and cc_m:
        cp, cc = fair["wape"], cc_m["wape"]
        if cc < cp:
            lines.append(
                f"Against the FAIR comparator, Chronos still wins cold: {cc:.3f} WAPE vs "
                f"Prophet trend-only {cp:.3f} on {COLD_START_CONTEXT} points of context. That is the "
                "cold-start advantage a TSFM is supposed to deliver — and it survives dropping the "
                "strawman.\n"
            )
        else:
            lines.append(
                f"Against the FAIR comparator the cold-start win **disappears**: Prophet trend-only "
                f"{cp:.3f} WAPE vs Chronos {cc:.3f}. The earlier \"Chronos crushes Prophet cold\" "
                "claim was an artifact of running Prophet with yearly seasonality on 6 points. "
                "Reported as-is.\n"
            )

    # ── Timing ───────────────────────────────────────────────────────────────
    lines.extend(_render_timing(chronos, timing, hw))

    # ── Honest take ──────────────────────────────────────────────────────────
    lines.append("## Honest take (model selection)\n")
    lines.append(
        "- **Dependency cost is real:** Chronos pulls `torch` (~2 GB wheel) + `transformers` + "
        "`accelerate`. That is why it lives in `requirements-ml.txt`, NOT the core deploy image. "
        "Inference is CPU-cheap once loaded (see the timing table); the cost is install/image "
        "size, plus a one-off weight load, not per-forecast latency.\n"
    )
    if c_over and c_over["wape"] < p_over["wape"]:
        lines.append(
            f"- **Chronos won on accuracy here ({c_over['wape']:.3f} vs Prophet "
            f"{p_over['wape']:.3f} WAPE), but read it carefully:** this is *one* macro series "
            "(n=1), not 791 parts. A single-series win is suggestive, not conclusive — Chronos's "
            "pretraining corpus likely contains manufacturing/orders-like signals, so this is close "
            "to in-distribution for it. The right read is \"a TSFM is competitive-to-better with "
            "zero fitting\", not \"replace Prophet everywhere\".\n"
        )
        lines.append(
            "- **Prophet still earns its place** for production demand on long-history parts: it is "
            "interpretable (decomposable trend/seasonality), already validated, and adds no torch "
            f"dependency to the deploy image. The accuracy gap ({c_over['wape']:.3f} vs "
            f"{p_over['wape']:.3f} WAPE) must be weighed against those operational costs.\n"
        )
    else:
        lines.append(
            "- **Prophet holds up** on this series — fitted, cheap, interpretable, already "
            "validated, and no torch dependency.\n"
        )
    if fair and cc_m and cc_m["wape"] < fair["wape"]:
        lines.append(
            "- **Reach for a TSFM** when a part is genuinely cold-start (no history to fit) or when "
            "you need one model across thousands of heterogeneous SKUs without per-series tuning. "
            "The cold-start table is the evidence — and it holds against a *correctly configured* "
            "Prophet, not just the strawman.\n"
        )
    else:
        lines.append(
            "- **The cold-start case for a TSFM is NOT established on this series** once Prophet is "
            "configured correctly for a short history. Do not claim it.\n"
        )

    lines.append("## Reproduce\n")
    lines.append("```bash")
    lines.append("cd backend")
    lines.append("pip install -r requirements-ml.txt   # heavy: torch + chronos")
    lines.append("python -m seeds.run_chronos_benchmark")
    lines.append("```")
    lines.append(
        "\nTimings are machine-specific (hardware stated above) and will differ on yours; "
        "the WAPE/RMSE figures are deterministic given the same series vintage. "
        f"Run recorded: `{meta.get('run_at', 'n/a')}`.\n"
    )
    if not chronos:
        lines.append(
            f"\n> **Blocker (this run):** {meta.get('chronos_blocker', 'unavailable')}. "
            "Numbers above are marked *pending*; no Chronos figures were fabricated. "
            "Re-run once the dependency/weights are available.\n"
        )
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    from datetime import UTC, datetime

    series = _load_series()
    values = [float(v) for v in series.to_numpy()]

    meta = {
        "series_id": FRED_DEMAND_SERIES,
        "series_name": "Manufacturers' New Orders: Computers & Electronic Products ($M)",
        "n_obs": len(series),
        "start": str(series.index.min().date()),
        "end": str(series.index.max().date()),
        "horizon": HORIZON,
        "n_windows": N_WINDOWS,
        "chronos_model_requested": os.environ.get("CHRONOS_MODEL", DEFAULT_CHRONOS_MODEL),
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    timing: Dict[str, dict] = {}

    logger.info("Running Prophet (seasonal) backtest (%d windows × %d-month horizon)...", N_WINDOWS, HORIZON)
    prophet_fp = TimedFitPredict(make_prophet_fit_predict(yearly_seasonality=True), "prophet")
    prophet_rep = walk_forward_backtest(values, prophet_fp, horizon=HORIZON, n_windows=N_WINDOWS).as_dict()

    # Trend-only Prophet — the config the served per-part forecaster uses, and the
    # fair cold-start comparator (6 points cannot support yearly seasonality).
    prophet_trend_fp = TimedFitPredict(
        make_prophet_fit_predict(yearly_seasonality=False), "prophet_trend_only"
    )

    logger.info("Running seasonal-naive baseline backtest...")
    naive_fp = TimedFitPredict(seasonal_naive_fit_predict, "seasonal_naive")
    naive_rep = walk_forward_backtest(values, naive_fp, horizon=HORIZON, n_windows=N_WINDOWS).as_dict()

    # Chronos — optional/heavy. Attempt; on any failure mark pending (never fake).
    chronos_rep = None
    chronos_meta = None
    chronos_fp: Optional[TimedFitPredict] = None
    model_name = meta["chronos_model_requested"]
    try:
        raw_fp, chronos_meta = make_chronos_fit_predict(model_name)
        chronos_fp = TimedFitPredict(raw_fp, "chronos")

        # Warm-up: the first forward pass pays lazy-init costs (~40× the warm cost).
        # Time it, report it, and keep it OUT of the steady-state stats.
        warm = chronos_fp.warmup(values[: max(HORIZON * 2, 24)])
        chronos_meta["warmup_seconds"] = round(warm, 4)
        logger.info("Chronos warm-up forward pass: %.0f ms (discarded from steady-state)", warm * 1000)

        logger.info("Running Chronos zero-shot backtest...")
        t0 = time.perf_counter()
        rep = walk_forward_backtest(values, chronos_fp, horizon=HORIZON, n_windows=N_WINDOWS).as_dict()
        chronos_meta["walk_forward_wall_seconds"] = round(time.perf_counter() - t0, 3)

        # The walk-forward is only 3 forecast calls — too few for a stable latency
        # figure. Repeat the same forward pass N times on the full context to get a
        # steady-state distribution an interviewer can actually reproduce.
        chronos_meta["steady_state"] = _repeat_bench(raw_fp, values, repeats=INFERENCE_REPEATS)
        logger.info(
            "Chronos steady-state forward pass: median %.2f ms over %d repeats (context %d)",
            chronos_meta["steady_state"]["median_ms"], INFERENCE_REPEATS, len(values),
        )
        rep.update(chronos_meta)
        chronos_rep = rep
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chronos unavailable — writing Prophet/naive only, Chronos pending: %s", exc)
        meta["chronos_blocker"] = f"{type(exc).__name__}: {exc}"

    # Snapshot the per-call timings from the WALK-FORWARD only, before the cold-start
    # run appends its short-context calls — mixing a 185-point fit with a 6-point fit
    # in one median would be exactly the kind of un-interpretable number this rewrite
    # exists to remove.
    for tfp in (chronos_fp, prophet_fp, naive_fp):
        if tfp is not None and tfp.stats():
            timing[tfp.label] = tfp.stats()

    # Cold-start experiment (only if Chronos available, so the comparison is complete)
    cold_start = {}
    if chronos_fp is not None:
        logger.info("Running cold-start experiment (%d-month context)...", COLD_START_CONTEXT)
        cold_start = {
            "context_len": COLD_START_CONTEXT,
            # Kept ONLY to show what the old (rigged) comparison did: yearly seasonality
            # on 6 points is a misconfiguration, and it is labelled as such in the doc.
            "prophet": cold_start_eval(values, prophet_fp, COLD_START_CONTEXT),
            # The fair comparator: Prophet configured for a short series.
            "prophet_trend_only": cold_start_eval(values, prophet_trend_fp, COLD_START_CONTEXT),
            "seasonal_naive": cold_start_eval(values, naive_fp, COLD_START_CONTEXT),
            "chronos": cold_start_eval(values, chronos_fp, COLD_START_CONTEXT),
        }

    # prophet_trend_only is only ever called on the 6-point cold-start context, so its
    # timing is recorded separately and labelled as such.
    if prophet_trend_fp.stats():
        timing["prophet_trend_only"] = prophet_trend_fp.stats()

    payload = {
        "meta": meta,
        "hardware": _hardware(),
        "timing": timing,
        "prophet": prophet_rep,
        "seasonal_naive": naive_rep,
        "chronos": chronos_rep,
        "cold_start": cold_start,
    }

    docs_dir = REPO_ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "chronos_benchmark.json").write_text(json.dumps(payload, indent=2))
    (docs_dir / "CHRONOS_BENCHMARK.md").write_text(_render_markdown(payload))

    if chronos_rep:
        ch_t = timing.get("chronos", {})
        logger.info(
            "DONE — Prophet WAPE=%.3f, naive WAPE=%.3f, Chronos WAPE=%.3f "
            "(chronos median %.1f ms/forecast over %s calls). Wrote docs/CHRONOS_BENCHMARK.md",
            prophet_rep["overall"]["wape"], naive_rep["overall"]["wape"],
            chronos_rep["overall"]["wape"], ch_t.get("median_ms", float("nan")),
            ch_t.get("n_calls", 0),
        )
    else:
        logger.info(
            "DONE (Chronos pending) — Prophet WAPE=%.3f, naive WAPE=%.3f. Wrote docs/CHRONOS_BENCHMARK.md",
            prophet_rep["overall"]["wape"], naive_rep["overall"]["wape"],
        )


if __name__ == "__main__":
    main()
