# Chronos (TSFM) Zero-Shot Benchmark vs Prophet

**Series:** Census M3 / FRED `A34SNO` (Manufacturers' New Orders: Computers & Electronic Products ($M)), monthly, 197 obs 2010-01-01 → 2026-05-01.

**Method:** the IDENTICAL rolling-origin walk-forward as [FORECAST_BACKTEST.md](FORECAST_BACKTEST.md) — 3 non-overlapping origins, 12-month horizon, same WAPE/MAPE/RMSE/bias metrics (`app.ml.backtest`, `app.ml.forecast_metrics`).

**Scope, plainly:** n = 1 macro series, 3 origins, 36 scored points, no confidence intervals. This is a build-vs-buy probe, not a production model-selection study — do not read a single-series WAPE gap as "model X is better".

**Chronos model:** `amazon/chronos-bolt-tiny` (8.65 M params) — run **zero-shot** (no fit, no training on this series). Point forecast = 0.5 quantile. CPU, torch 2.12.1. Full timing breakdown below.

## Headline (full-history walk-forward)

| Model | WAPE | MAPE | RMSE | Bias | Zero-shot? |
|---|---:|---:|---:|---:|:--:|
| **Prophet** (fitted, seasonal) | 0.027 | 0.025 | 1177.08 | -567.89 | no |
| Seasonal-naive (m=12) | 0.044 | 0.042 | 1500.20 | -1062.17 | n/a |
| **Chronos** chronos-bolt-tiny | 0.029 | 0.028 | 1169.17 | -767.41 | **yes** |

**Verdict: Prophet WINS overall** (0.027 WAPE vs Chronos 0.029, Chronos is 10.2% worse). On a long, clean, strongly-seasonal series the fitted model is hard to beat — the TSFM's dependency weight (torch, ~2 GB) is not justified for THIS series. Chronos does clear the seasonal-naive bar (0.029 vs naive 0.044).

## WAPE by horizon (where each model degrades)

| Horizon (months ahead) | Prophet | Seasonal-naive | Chronos (zero-shot) |
|---:|---:|---:|---:|
| 1 | 0.015 | 0.031 | 0.007 |
| 2 | 0.012 | 0.035 | 0.011 |
| 3 | 0.012 | 0.026 | 0.009 |
| 4 | 0.011 | 0.022 | 0.017 |
| 5 | 0.013 | 0.028 | 0.019 |
| 6 | 0.013 | 0.028 | 0.018 |
| 7 | 0.027 | 0.043 | 0.029 |
| 8 | 0.035 | 0.052 | 0.039 |
| 9 | 0.036 | 0.054 | 0.041 |
| 10 | 0.046 | 0.066 | 0.049 |
| 11 | 0.047 | 0.067 | 0.050 |
| 12 | 0.050 | 0.068 | 0.057 |

## Cold-start: only 6 months of history (< 1 season)

The natural TSFM case: a brand-new part with almost no demand history. Each model sees only the most recent **6** points before each holdout block (same blocks as above).

**Two Prophet rows, deliberately.** Handing Prophet 6 points *with yearly seasonality still switched on* is a strawman — it is a misconfiguration, not a defeat, and an earlier version of this doc quietly used it to make Chronos look good. The honest comparator is Prophet configured the way you would actually configure it for 6 points (trend-only) — which is also the config the served per-part forecaster uses.

| Model | Cold-start WAPE | Cold-start RMSE | Cold-start bias |
|---|---:|---:|---:|
| Prophet (seasonal — MISCONFIGURED for 6 pts, shown for honesty) | 10.509 | 396755.78 | -125632.59 |
| Prophet (trend-only — the fair comparator) | 0.018 | 571.87 | -109.55 |
| Seasonal-naive | 0.038 | 1430.12 | -1008.36 |
| Chronos (zero-shot) | 0.039 | 1410.53 | -1034.29 |

Against the FAIR comparator the cold-start win **disappears**: Prophet trend-only 0.018 WAPE vs Chronos 0.039. The earlier "Chronos crushes Prophet cold" claim was an artifact of running Prophet with yearly seasonality on 6 points. Reported as-is.

## Cost / timing (measured this run, not quoted)

**Hardware:** macOS-26.5-arm64-arm-64bit-Mach-O · arm · Python 3.13.5 · torch 2.12.1 (4 threads) · device `cpu` · CUDA available: False.

**Chronos startup:** `import torch` + `import chronos` **2.24 s** · `from_pretrained` **0.24 s** (weights already in the HF cache: **True** — a cold machine must first download ~33 MB) · model size **8.65 M** parameters.

**Warm-up:** the first forward pass costs **7 ms** (lazy init). It is timed separately and EXCLUDED from the steady-state numbers below — reporting it inside a single wall-clock, as this benchmark used to, is what made the old "0.01 s inference" figure impossible to interpret.

Per-call cost over the walk-forward origins (warm-up excluded; the trend-only row is the short-context cold-start run and is timed separately so the medians are not mixed):

| Model | Calls | Context (pts) | Median / call | Mean | Min | Max | What one call does |
|---|---:|---:|---:|---:|---:|---:|---|
| Chronos (zero-shot) | 3 | 161–185 | **3.0 ms** | 3.2 ms | 2.9 ms | 3.8 ms | frozen forward pass, H=12 |
| Prophet (seasonal) | 3 | 161–185 | **29.1 ms** | 31.6 ms | 24.8 ms | 41.0 ms | full Stan fit + predict |
| Prophet (trend-only, cold-start ctx) | 3 | 6 | **34.8 ms** | 34.0 ms | 32.0 ms | 35.2 ms | full Stan fit + predict |
| Seasonal-naive | 3 | 161–185 | **0.0 ms** | 0.0 ms | 0.0 ms | 0.0 ms | array indexing |

**Chronos steady-state latency** (the walk-forward is only 3 calls — not a latency sample): the same forward pass repeated **20×** on the full 197-point context, after a discarded warm-up → median **2.64 ms**, mean 2.80 ms, p95 3.80 ms, range 2.43–3.80 ms (H=12, batch 1). An 8.65 M-parameter encoder-decoder doing ONE non-autoregressive forward pass over ~200 tokens really is single-digit milliseconds on this CPU — the number is small, but it is not a stub: dropping `chronos-forecasting` makes this script fail loudly and write "pending" rather than produce figures.

Chronos's per-forecast cost is **10× cheaper than Prophet's** here — but that compares a frozen forward pass against a full Stan fit, which is exactly the point: the TSFM's cost is the ~2 GB torch install and the one-off weight load, not the inference. (Horizon 12, single series, batch size 1, n=3 calls — this is NOT a throughput benchmark, and with so few calls the median is indicative, not a stable percentile.)

## Honest take (model selection)

- **Dependency cost is real:** Chronos pulls `torch` (~2 GB wheel) + `transformers` + `accelerate`. That is why it lives in `requirements-ml.txt`, NOT the core deploy image. Inference is CPU-cheap once loaded (see the timing table); the cost is install/image size, plus a one-off weight load, not per-forecast latency.

- **Prophet holds up** on this series — fitted, cheap, interpretable, already validated, and no torch dependency.

- **The cold-start case for a TSFM is NOT established on this series** once Prophet is configured correctly for a short history. Do not claim it.

## Reproduce

```bash
cd backend
pip install -r requirements-ml.txt   # heavy: torch + chronos
python -m seeds.run_chronos_benchmark
```

Timings are machine-specific (hardware stated above) and will differ on yours; the WAPE/RMSE figures are deterministic given the same series vintage. Run recorded: `2026-07-13T03:20:45+00:00`.
