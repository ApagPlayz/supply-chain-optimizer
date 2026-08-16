"""Shared constants for the REAL macro demand series used by the kept backtests.

`seeds/run_forecast_backtest.py` and `seeds/run_chronos_benchmark.py` both score
models against Census M3 `A34SNO` — an actually-observed macro demand series, as
opposed to the retired `seeds/train_forecasts.py` per-part seed (deleted; its
demand magnitude was derived from inventory/risk, not observed). This module
exists only to give those two backtests (plus their tests) a home for the series
id and on-disk cache path that does not depend on the deleted module.
"""
from pathlib import Path

# Census M3 "Manufacturers' New Orders: Computers & Electronic Products" ($M, monthly,
# 1992->now) — the real macro *demand* target, served keyless via the FRED CSV endpoint.
FRED_DEMAND_SERIES = "A34SNO"
CACHE_PATH = Path(__file__).resolve().parent / "data" / "a34sno_monthly.csv"
