"""
FRED data client + feature engineering for macro stress detection.

Six FRED series covering semiconductor supply chain health:
  PCU33443344   — PPI: Semiconductor & Electronic Component Manufacturing
  CAPUTLG3344S  — Capacity Utilization: Semiconductors (%)
  ISRATIO       — Total Business Inventory-to-Sales Ratio
  IPG3344S      — Industrial Production: Semiconductors
  IZ3344        — Import Price Index: Electronic Components
  TSIFRGHT      — Freight Transportation Services Index

Stress regime: capacity_util >= 75 AND inventory_ratio <= 1.35.
This combination correctly identifies the 2021-2022 chip shortage when
trained on pre-2021 data (validated in test_regime_model.py).

Source: St. Louis Federal Reserve (fred.stlouisfed.org), free API.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Series names → FRED series IDs
FRED_SERIES: dict[str, str] = {
    "ppi_semis":       "PCU33443344",
    "capacity_util":   "CAPUTLG3344S",
    "inventory_ratio": "ISRATIO",
    "industrial_prod": "IPG3344S",
    "import_price":    "IZ3344",
    "freight_tsi":     "TSIFRGHT",
}

# Stress regime thresholds (literature-derived, validated on 2021-2022 shortage)
STRESS_CAPACITY_THRESHOLD = 75.0   # % — US semiconductor fab utilization
STRESS_INVENTORY_THRESHOLD = 1.35  # ratio — below this = inventory depletion


def fetch_fred_data(api_key: str, start: str = "2010-01-01") -> Optional[pd.DataFrame]:
    """
    Pull all six FRED series and align to monthly frequency.
    Returns None if api_key is empty or the pull fails.
    """
    if not api_key:
        logger.warning("FRED_API_KEY not set — macro stress will use fallback of 0.0")
        return None
    try:
        from fredapi import Fred  # optional dependency
        fred = Fred(api_key=api_key)
        frames: dict[str, pd.Series] = {}
        for name, series_id in FRED_SERIES.items():
            s = fred.get_series(series_id, observation_start=start)
            frames[name] = s
        df = pd.DataFrame(frames)
        df = df.resample("MS").last().ffill()
        return df.dropna(how="all")
    except Exception as exc:
        logger.error("FRED pull failed: %s", exc)
        return None


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each of the 6 FRED series produce 3 features:
      - _level  : raw value (normalised later by StandardScaler in the pipeline)
      - _mom3   : 3-month percentage change (momentum signal)
      - _z12    : 12-month rolling z-score (deviation from recent trend)

    Returns a DataFrame with 18 columns and no NaN rows.
    Drops the first 12 rows where rolling stats are unavailable.
    """
    cols = []
    for col in FRED_SERIES.keys():
        if col not in df.columns:
            continue
        series = df[col]
        cols.append(series.rename(f"{col}_level"))
        cols.append(series.pct_change(3).rename(f"{col}_mom3"))
        rolling_mean = series.rolling(12).mean()
        rolling_std = series.rolling(12).std().replace(0.0, 1.0)
        z = (series - rolling_mean) / rolling_std
        cols.append(z.rename(f"{col}_z12"))
    return pd.concat(cols, axis=1).dropna()


def compute_stress_label(df: pd.DataFrame) -> pd.Series:
    """
    Binary stress regime label.
    1 = semiconductor shortage stress conditions present.
    0 = normal conditions.

    Criterion: US semiconductor fab utilization >= 75% AND
               total business inventory/sales ratio <= 1.35.

    Validated: fires during 2021-01 through 2022-12 (chip shortage holdout).
    Source: Camur et al. 2023 arXiv:2306.01837; CAPUTLG3344S/ISRATIO threshold
            derived from pre-2021 historical analysis.
    """
    cap = df["capacity_util"] >= STRESS_CAPACITY_THRESHOLD
    inv = df["inventory_ratio"] <= STRESS_INVENTORY_THRESHOLD
    return (cap & inv).astype(int).rename("stress_regime")
