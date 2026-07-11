# Demand Forecast — Walk-Forward Backtest

**Series:** Census M3 / FRED `A34SNO` (Manufacturers' New Orders: Computers & Electronic Products, $M), monthly, 197 obs 2010-01-01 → 2026-05-01.

**Method:** rolling-origin walk-forward — 3 non-overlapping origins, 12-month horizon each. Models retrained at every origin.

**Baseline:** seasonal-naive (m=12). Prophet must beat this to justify its complexity.

## Headline

- **Prophet (seasonal) WAPE:** 0.027  ·  MAPE 0.025  ·  RMSE 1179.02
- **Prophet (served config, trend-only) WAPE:** 0.025  ·  MAPE 0.024  ·  RMSE 1164.41  ·  skill +42.7%
- **Seasonal-naive WAPE:** 0.044  ·  MAPE 0.042  ·  RMSE 1501.68
- **Skill score (1 − WAPE_prophet/WAPE_naive):** +39.3%
- **Verdict:** Prophet beats the seasonal-naive baseline.

## Accuracy degradation by horizon (WAPE)

| Horizon (months ahead) | Prophet WAPE | Naive WAPE | Prophet bias |
|---:|---:|---:|---:|
| 1 | 0.015 | 0.031 | -53.87 |
| 2 | 0.012 | 0.035 | -190.39 |
| 3 | 0.012 | 0.026 | -182.42 |
| 4 | 0.011 | 0.022 | -289.02 |
| 5 | 0.013 | 0.028 | -341.34 |
| 6 | 0.013 | 0.028 | -109.88 |
| 7 | 0.027 | 0.043 | -501.85 |
| 8 | 0.035 | 0.052 | -918.19 |
| 9 | 0.036 | 0.054 | -958.05 |
| 10 | 0.046 | 0.066 | -1239.52 |
| 11 | 0.047 | 0.067 | -915.18 |
| 12 | 0.050 | 0.068 | -1122.57 |

## Notes

- WAPE (Σ|a−f|/Σ|a|) is the headline metric; it does not blow up on low-volume months the way MAPE can.
- `bias` is mean(forecast − actual): positive ⇒ systematic over-forecast.
- Reproduce: `cd backend && python -m seeds.run_forecast_backtest`.
