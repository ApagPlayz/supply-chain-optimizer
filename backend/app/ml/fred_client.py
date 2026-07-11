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

import io
import logging
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Committed real-data cache (offline fallback + reproducible training input).
SEED_DATA_DIR = Path(__file__).resolve().parents[2] / "seeds" / "data"

# Public CSV download endpoint — serves the same observations as the API but
# requires NO API key. Used to source real demand data without a user secret.
FREDGRAPH_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

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


# ── Keyless single-series download (no FRED_API_KEY required) ────────────────


def parse_fred_csv(raw: str, series_id: str) -> pd.Series:
    """Parse fredgraph.csv text into a date-indexed float Series.

    The CSV has two columns: an observation-date column and the series column.
    Missing observations are encoded as ``.`` by FRED and become NaN, which we
    drop so callers always get a clean numeric series.
    """
    df = pd.read_csv(io.StringIO(raw))
    if df.shape[1] < 2:
        raise ValueError(f"unexpected FRED CSV layout for {series_id}: columns={list(df.columns)}")
    date_col, val_col = df.columns[0], df.columns[1]
    idx = pd.to_datetime(df[date_col])
    vals = pd.to_numeric(df[val_col], errors="coerce")  # FRED's '.' missing marker -> NaN
    return pd.Series(vals.to_numpy(), index=idx, name=series_id).dropna()


def fetch_fred_series_csv(
    series_id: str, start: str = "2010-01-01", timeout: int = 30
) -> Optional[pd.Series]:
    """Download one FRED series via the public CSV endpoint — NO API key needed.

    Returns a date-indexed float Series, or None if the download/parse fails
    (e.g. offline). Callers should fall back to a cached snapshot in that case.
    """
    url = f"{FREDGRAPH_CSV_URL}?id={series_id}&cosd={start}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed gov host)
            raw = resp.read().decode("utf-8")
        series = parse_fred_csv(raw, series_id)
        if series.empty:
            logger.warning("keyless FRED CSV for %s parsed to an empty series", series_id)
            return None
        return series
    except Exception as exc:
        logger.warning("keyless FRED CSV fetch failed for %s: %s", series_id, exc)
        return None


def build_weekly_demand_shape(monthly: pd.Series, weeks: int = 52) -> np.ndarray:
    """Turn a monthly macro series into a `weeks`-long demand SHAPE (mean == 1.0).

    The most recent ``weeks`` observations are resampled monthly→weekly with
    linear interpolation, then divided by their own mean so the result is a
    unit-mean multiplier. Multiplying a per-component baseline by this shape
    injects the *real* temporal dynamics (trend + the 2021-22 chip-shortage
    spike) of the source series without fabricating any noise.

    Raises ValueError if the input is empty or non-positive on average.
    """
    if monthly is None or len(monthly) == 0:
        raise ValueError("cannot build demand shape from an empty series")
    weekly = monthly.sort_index().resample("W").interpolate(method="linear").dropna()
    if len(weekly) < weeks:
        # Not enough weekly points after interpolation — pad from the front by
        # repeating the earliest available value (keeps length contract).
        pad = np.full(weeks - len(weekly), float(weekly.iloc[0]))
        tail = weekly.to_numpy(dtype=float)
        arr = np.concatenate([pad, tail])
    else:
        arr = weekly.to_numpy(dtype=float)[-weeks:]
    mean = float(np.mean(arr))
    if mean <= 0:
        raise ValueError("demand shape mean is non-positive — source series invalid")
    return arr / mean


# ═══════════════════════════════════════════════════════════════════════════
# GSCPI regime target + lagged FRED regime features (Route A — real observed)
# ═══════════════════════════════════════════════════════════════════════════
#
# The legacy `compute_stress_label` above is a TAUTOLOGY: the label is a
# threshold on `capacity_util` / `inventory_ratio`, which are themselves model
# inputs, so recall is ~1.0 by construction. Route A replaces it with an
# INDEPENDENT, externally-published target — the NY Fed Global Supply Chain
# Pressure Index (GSCPI) — and forecasts next-month regime from *strictly
# lagged* real FRED series (+ an autoregressive GSCPI term). GSCPI is built by
# the NY Fed from global transportation costs (Baltic Dry, Harpex, air freight)
# and PMI supplier-delivery/backlog subcomponents — a different data domain from
# the US-semiconductor FRED features below, so no feature is a function of the
# label. See regime_model.py for training + the honest baseline comparison.

# NY Fed GSCPI download. The URL says .xlsx but the payload is a legacy OLE2
# .xls workbook, so it must be read with the xlrd engine (NOT openpyxl).
GSCPI_XLS_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/"
    "gscpi/downloads/gscpi_data.xlsx"
)
GSCPI_SHEET = "GSCPI Monthly Data"
GSCPI_CACHE = SEED_DATA_DIR / "gscpi_monthly.csv"

# Independent macro features for the regime forecast — strictly lagged at train
# time (see engineer_regime_features). All keyless FRED CSV series.
REGIME_FEATURE_SERIES: dict[str, str] = {
    "capacity_util": "CAPUTLG3344S",  # Capacity Utilization: Semiconductors (%)
    "inv_sales":     "U34SIS",        # Inventories/Sales: Computers & Electronic Products
    "ip_semis":      "IPG3344S",      # Industrial Production: Semiconductors
    "mfg_inv_ratio": "MNFCTRIRSA",    # Total Manufacturing Inventories/Sales Ratio
}
REGIME_FEATURE_CACHE = SEED_DATA_DIR / "regime_features_monthly.csv"

# Regime bands on the GSCPI z-score (the index is already standardised ~N(0,1)).
# Pre-registered, independent of any feature or train/val split.
REGIME_BANDS = (-0.5, 0.5)          # (calm|elevated cut, elevated|stress cut)
REGIME_CLASSES = ["calm", "elevated", "stress"]


def _to_month_start(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Normalise any monthly index to the first-of-month timestamp."""
    return idx.to_period("M").to_timestamp()


def fetch_gscpi(timeout: int = 60, use_cache: bool = True) -> Optional[pd.Series]:
    """Download the NY Fed GSCPI monthly z-score series (1998→present).

    Reads the legacy OLE2 workbook with the xlrd engine, normalises to a
    month-start DatetimeIndex, refreshes the committed CSV cache under
    ``seeds/data/``, and returns a float Series named ``gscpi``. Falls back to
    the cached CSV if the download fails (e.g. offline). Returns None if neither
    source is available.
    """
    series: Optional[pd.Series] = None
    try:
        req = urllib.request.Request(GSCPI_XLS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed gov host)
            raw = resp.read()
        df = pd.read_excel(
            io.BytesIO(raw), sheet_name=GSCPI_SHEET, engine="xlrd",
            header=None, skiprows=5, usecols=[0, 1], names=["date", "gscpi"],
        )
        dates = pd.to_datetime(df["date"], errors="coerce")
        vals = pd.to_numeric(df["gscpi"], errors="coerce")
        s = pd.Series(vals.to_numpy(), index=dates, name="gscpi").dropna()
        s.index = _to_month_start(pd.DatetimeIndex(s.index))
        series = s.sort_index()
        try:
            SEED_DATA_DIR.mkdir(parents=True, exist_ok=True)
            series.to_frame().to_csv(GSCPI_CACHE, index_label="date")
        except Exception as exc:  # noqa: BLE001 - cache write is best-effort
            logger.warning("could not refresh GSCPI cache: %s", exc)
    except Exception as exc:  # noqa: BLE001 - fall back to committed cache
        logger.warning("GSCPI download failed (%s) — trying cache %s", exc, GSCPI_CACHE)

    if series is None and use_cache and GSCPI_CACHE.exists():
        cached = pd.read_csv(GSCPI_CACHE, parse_dates=["date"]).set_index("date")["gscpi"]
        cached.index = _to_month_start(pd.DatetimeIndex(cached.index))
        series = cached.sort_index()

    if series is None or series.empty:
        logger.error("GSCPI unavailable from both network and cache")
        return None
    return series


def gscpi_regime_label(gscpi: pd.Series, bands: tuple[float, float] = REGIME_BANDS) -> pd.Series:
    """Map the GSCPI z-score to the calm / elevated / stress regime label.

    This is the model's TARGET. It is a function of GSCPI ONLY — none of the
    FRED features enter it — so the classification task is not definitional.
    """
    lo, hi = bands
    lab = pd.cut(gscpi, [-np.inf, lo, hi, np.inf], labels=REGIME_CLASSES)
    return pd.Series(lab.astype(str), index=gscpi.index, name="regime")


def fetch_regime_feature_frame(
    start: str = "1997-01-01", use_cache: bool = True
) -> Optional[pd.DataFrame]:
    """Pull the raw monthly FRED feature series via the keyless CSV endpoint.

    Returns a month-start-indexed DataFrame (one column per
    REGIME_FEATURE_SERIES key), refreshing the committed CSV cache. Falls back
    to the cache when any series fails to download. Returns None if unavailable.
    """
    frames: dict[str, pd.Series] = {}
    for name, series_id in REGIME_FEATURE_SERIES.items():
        s = fetch_fred_series_csv(series_id, start=start)
        if s is not None and not s.empty:
            s.index = _to_month_start(pd.DatetimeIndex(s.index))
            frames[name] = s.sort_index()

    if len(frames) == len(REGIME_FEATURE_SERIES):
        df = pd.DataFrame(frames).sort_index()
        try:
            SEED_DATA_DIR.mkdir(parents=True, exist_ok=True)
            df.to_csv(REGIME_FEATURE_CACHE, index_label="date")
        except Exception as exc:  # noqa: BLE001 - cache write is best-effort
            logger.warning("could not refresh regime-feature cache: %s", exc)
        return df

    if use_cache and REGIME_FEATURE_CACHE.exists():
        logger.warning("regime features incomplete online — using cache %s", REGIME_FEATURE_CACHE)
        df = pd.read_csv(REGIME_FEATURE_CACHE, parse_dates=["date"]).set_index("date")
        df.index = _to_month_start(pd.DatetimeIndex(df.index))
        return df.sort_index()

    logger.error("regime features unavailable from both network and cache")
    return None


def engineer_regime_features(raw: pd.DataFrame, gscpi: pd.Series) -> pd.DataFrame:
    """Build the STRICTLY LAGGED feature matrix for the next-month forecast.

    For each raw FRED series produce _level, _mom3 (3-month % change) and _z12
    (12-month rolling z-score), then shift the whole block by one month so a row
    dated *t* only contains information observable at *t-1* (no contemporaneous
    leakage from the target). Adds an autoregressive block of lagged GSCPI values
    (lag 1/2/3 and a 3-month change) — these are observed inputs at prediction
    time, not the label, so the persistence baseline is a nested special case the
    model can be measured against.

    Returns a feature-only DataFrame (no label column), NaN rows dropped.
    """
    cols = []
    for name in REGIME_FEATURE_SERIES:
        if name not in raw.columns:
            continue
        s = raw[name]
        cols.append(s.rename(f"{name}_level"))
        cols.append(s.pct_change(3, fill_method=None).rename(f"{name}_mom3"))
        rmean = s.rolling(12).mean()
        rstd = s.rolling(12).std().replace(0.0, np.nan)
        cols.append(((s - rmean) / rstd).rename(f"{name}_z12"))
    fred_block = pd.concat(cols, axis=1).replace([np.inf, -np.inf], np.nan)
    fred_block = fred_block.shift(1)  # strict 1-month lag — no contemporaneous target leakage

    ar_block = pd.DataFrame({
        "gscpi_lag1": gscpi.shift(1),
        "gscpi_lag2": gscpi.shift(2),
        "gscpi_lag3": gscpi.shift(3),
        "gscpi_chg3": gscpi.shift(1) - gscpi.shift(4),
    })
    return ar_block.join(fred_block, how="outer").dropna()
