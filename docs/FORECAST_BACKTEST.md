# Demand Forecast — Walk-Forward Backtest

**Series:** FRED `IPG3344S` (Industrial Production: Semiconductors), monthly, 197 obs 2010-01-01 → 2026-05-01.

**Method:** rolling-origin walk-forward — 3 non-overlapping origins, 12-month horizon each. Models retrained at every origin.

**Baseline:** seasonal-naive (m=12). Prophet must beat this to justify its complexity.

## Headline

- **Prophet WAPE:** 0.048  ·  MAPE 0.044  ·  RMSE 9.86
- **Seasonal-naive WAPE:** 0.087  ·  MAPE 0.084  ·  RMSE 15.35
- **Skill score (1 − WAPE_prophet/WAPE_naive):** +45.2%
- **Verdict:** Prophet beats the seasonal-naive baseline.

## Accuracy degradation by horizon (WAPE)

| Horizon (months ahead) | Prophet WAPE | Naive WAPE | Prophet bias |
|---:|---:|---:|---:|
| 1 | 0.020 | 0.072 | -2.51 |
| 2 | 0.037 | 0.088 | -5.54 |
| 3 | 0.044 | 0.080 | -5.56 |
| 4 | 0.033 | 0.071 | -2.61 |
| 5 | 0.036 | 0.080 | -4.00 |
| 6 | 0.031 | 0.080 | -3.74 |
| 7 | 0.032 | 0.086 | -4.17 |
| 8 | 0.059 | 0.099 | -8.86 |
| 9 | 0.060 | 0.090 | -7.86 |
| 10 | 0.064 | 0.095 | -8.44 |
| 11 | 0.071 | 0.098 | -11.64 |
| 12 | 0.080 | 0.105 | -13.23 |

## Notes

- WAPE (Σ|a−f|/Σ|a|) is the headline metric; it does not blow up on low-volume months the way MAPE can.
- `bias` is mean(forecast − actual): positive ⇒ systematic over-forecast.
- Reproduce: `cd backend && python -m seeds.run_forecast_backtest`.
