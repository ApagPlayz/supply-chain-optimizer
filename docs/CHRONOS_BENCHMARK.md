# Chronos (TSFM) Zero-Shot Benchmark vs Prophet

**Series:** FRED `IPG3344S` (Industrial Production: Semiconductors), monthly, 197 obs 2010-01-01 → 2026-05-01.

**Method:** the IDENTICAL rolling-origin walk-forward as [FORECAST_BACKTEST.md](FORECAST_BACKTEST.md) — 3 non-overlapping origins, 12-month horizon, same WAPE/MAPE/RMSE/bias metrics (`app.ml.backtest`, `app.ml.forecast_metrics`).

**Chronos model:** `amazon/chronos-bolt-tiny` — run **zero-shot** (no fit, no training on this series). Point forecast = 0.5 quantile. CPU, torch 2.12.1, load 0.25s.

## Headline (full-history walk-forward)

| Model | WAPE | MAPE | RMSE | Bias | Zero-shot? |
|---|---:|---:|---:|---:|:--:|
| **Prophet** (fitted) | 0.048 | 0.044 | 9.86 | -6.51 | no |
| Seasonal-naive (m=12) | 0.087 | 0.084 | 15.35 | -13.50 | n/a |
| **Chronos** chronos-bolt-tiny | 0.026 | 0.026 | 5.00 | -0.39 | **yes** |

**Verdict: Chronos zero-shot WINS overall** (0.026 WAPE vs Prophet 0.048, +45.4%). A TSFM with no fitting beats a tuned Prophet on this series. Chronos does clear the seasonal-naive bar (0.026 vs naive 0.087).

## WAPE by horizon (where each model degrades)

| Horizon (months ahead) | Prophet | Seasonal-naive | Chronos (zero-shot) |
|---:|---:|---:|---:|
| 1 | 0.020 | 0.072 | 0.032 |
| 2 | 0.037 | 0.088 | 0.022 |
| 3 | 0.044 | 0.080 | 0.009 |
| 4 | 0.033 | 0.071 | 0.028 |
| 5 | 0.036 | 0.080 | 0.014 |
| 6 | 0.031 | 0.080 | 0.016 |
| 7 | 0.032 | 0.086 | 0.013 |
| 8 | 0.059 | 0.099 | 0.025 |
| 9 | 0.060 | 0.090 | 0.027 |
| 10 | 0.064 | 0.095 | 0.029 |
| 11 | 0.071 | 0.098 | 0.041 |
| 12 | 0.080 | 0.105 | 0.053 |

## Cold-start: only 6 months of history (< 1 season)

The natural TSFM case: a brand-new part with almost no demand history. Each model sees only the most recent **6** points before each holdout block (same blocks as above). Prophet cannot learn yearly seasonality from < 1 season; Chronos carries a learned prior from pretraining and needs no fit.

| Model | Cold-start WAPE | Cold-start RMSE | Cold-start bias |
|---|---:|---:|---:|
| Prophet (fitted) | 4.527 | 1053.02 | +159.78 |
| Seasonal-naive | 0.058 | 11.86 | -8.59 |
| Chronos (zero-shot) | 0.054 | 11.25 | -7.98 |

With only 6 months of context Chronos (0.054 WAPE) beats Prophet (4.527) — the cold-start advantage a TSFM is supposed to deliver, confirmed on real data.

## Honest take (model selection)

- **Dependency cost is real:** Chronos pulls `torch` (~2 GB wheel) + `transformers` + `accelerate`. That is why it lives in `requirements-ml.txt`, NOT the core deploy image. Inference is CPU-cheap once loaded; the cost is install/image size, not latency.

- **Chronos won on accuracy here, but read it carefully:** this is *one* macro series (n=1), not 791 parts. A single-series win is suggestive, not conclusive — Chronos's pretraining corpus likely contains industrial-production-like signals, so this is close to in-distribution for it. The right read is "a TSFM is competitive-to-better with zero fitting", not "replace Prophet everywhere".

- **Prophet still earns its place** for production demand on long-history parts: it is interpretable (decomposable trend/seasonality), already validated, and adds no torch dependency to the deploy image. Accuracy gap (0.026 vs 0.048 WAPE) must be weighed against those operational costs.

- **Reach for a TSFM** when a part is genuinely cold-start (no history to fit) or when you need one model across thousands of heterogeneous SKUs without per-series tuning. The cold-start table above is the hard evidence for *when* the dependency weight pays off: with only 6 months of history Prophet collapses (WAPE blows up) while Chronos zero-shot stays usable.

## Reproduce

```bash
cd backend
pip install -r requirements-ml.txt   # heavy: torch + chronos
python -m seeds.run_chronos_benchmark
```