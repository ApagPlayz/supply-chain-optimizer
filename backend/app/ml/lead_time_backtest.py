"""
Historical aggregate lead-time backtest (Route A, Track L).

While the per-part collector panel accumulates, this module produces a REAL
historical result: it predicts the reconstructed Susquehanna Financial Group
(SFG) industry-aggregate semiconductor lead-time series from *lagged* macro
supply-chain features that are known months earlier.

Target  (real, sparse anchors — see seeds/data/lead_time_aggregate_susquehanna.csv):
    SFG monthly aggregate lead time in weeks, 2021-02 .. 2023-03.
Features (real, keyless):
    - NY Fed GSCPI  (Global Supply Chain Pressure Index), lagged L months
    - FRED IPG3344S (Industrial Production: Semiconductors), lagged L months

Because supply-chain pressure LEADS observed lead times, we lag the features so
the model uses only information available before each lead-time reading — i.e.
this is a genuine forecast, not a same-month fit. Sample size is small (~12
anchor months), so we report leave-one-out cross-validation against a
predict-the-mean baseline and state the small-N caveat honestly.

Run:
    cd backend
    python -m app.ml.lead_time_backtest
"""
from __future__ import annotations

import io
import logging
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "seeds" / "data"
AGGREGATE_CSV = _DATA_DIR / "lead_time_aggregate_susquehanna.csv"
IPG_CSV = _DATA_DIR / "ipg3344s_monthly.csv"

GSCPI_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/"
    "gscpi/downloads/gscpi_data.xlsx"
)

DEFAULT_LAG_MONTHS = 3


def load_aggregate() -> pd.Series:
    """Load the SFG aggregate lead-time anchors as a month-indexed Series (weeks)."""
    df = pd.read_csv(AGGREGATE_CSV, comment="#")
    idx = pd.to_datetime(df["month"])
    return pd.Series(df["lead_time_weeks"].to_numpy(float), index=idx, name="lead_time_weeks").sort_index()


def load_gscpi(timeout: int = 25) -> Optional[pd.Series]:
    """Fetch NY Fed GSCPI (keyless .xlsx) as a month-start-indexed Series, or None."""
    try:
        with urllib.request.urlopen(GSCPI_URL, timeout=timeout) as r:  # noqa: S310 (fixed gov host)
            raw = r.read()
        df = pd.read_excel(io.BytesIO(raw), sheet_name="GSCPI Monthly Data")
        idx = pd.to_datetime(df["Date"]).dt.to_period("M").dt.to_timestamp()  # -> month start
        s = pd.Series(df["GSCPI"].to_numpy(float), index=idx, name="gscpi")
        return s[~s.index.duplicated(keep="last")].sort_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("GSCPI fetch failed (%s) — backtest will fall back to IPG3344S only", exc)
        return None


def load_ipg() -> Optional[pd.Series]:
    """FRED IPG3344S (Industrial Production: Semiconductors).

    Fetches live from the keyless FRED CSV endpoint (and re-caches locally);
    falls back to the local cache only if the network fetch fails.
    """
    from app.ml.fred_client import fetch_fred_series_csv

    series = fetch_fred_series_csv("IPG3344S", start="1998-01-01")
    if series is not None and not series.empty:
        series = series.rename("ipg3344s").sort_index()
        try:  # best-effort cache refresh
            IPG_CSV.parent.mkdir(parents=True, exist_ok=True)
            series.rename_axis("observation_date").rename("IPG3344S").to_csv(IPG_CSV)
        except Exception:  # noqa: BLE001
            pass
        return series
    try:
        df = pd.read_csv(IPG_CSV)
        idx = pd.to_datetime(df["observation_date"])
        return pd.Series(df["IPG3344S"].to_numpy(float), index=idx, name="ipg3344s").sort_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("IPG3344S unavailable (live fetch + cache both failed): %s", exc)
        return None


def _build_matrix(lag: int):
    """
    Align lagged features to the SFG anchor months.
    Returns (X, y, feature_names, aligned_index) using whatever features loaded.
    """
    target = load_aggregate()
    feats = {}
    gscpi = load_gscpi()
    if gscpi is not None:
        feats["gscpi_lag"] = gscpi.shift(lag)
    ipg = load_ipg()
    if ipg is not None:
        feats["ipg_lag"] = ipg.shift(lag)
    if not feats:
        raise RuntimeError("no feature series available (GSCPI + IPG3344S both failed to load)")

    fdf = pd.DataFrame(feats)
    # Reindex features onto the (month-start) target dates.
    fdf = fdf.reindex(target.index)
    joined = pd.concat([target, fdf], axis=1).dropna()
    y = joined["lead_time_weeks"].to_numpy(float)
    feat_cols = list(fdf.columns)
    X = joined[feat_cols].to_numpy(float)
    return X, y, feat_cols, joined.index


def run_backtest(lag: int = DEFAULT_LAG_MONTHS) -> dict:
    """
    Leave-one-out backtest of a Ridge regressor predicting the SFG aggregate
    lead time from lagged macro features. Returns a dict of REAL metrics.
    """
    X, y, feat_cols, idx = _build_matrix(lag)
    n = len(y)
    result = {
        "n_samples": int(n),
        "features": feat_cols,
        "lag_months": lag,
        "date_range": [str(idx.min().date()), str(idx.max().date())] if n else [],
    }
    if n < 4:
        result["status"] = "insufficient_overlap"
        return result

    # Real Pearson correlations (feature-lagged vs. observed lead time).
    result["pearson_corr"] = {
        c: round(float(np.corrcoef(X[:, i], y)[0, 1]), 3)
        for i, c in enumerate(feat_cols)
    }

    # Leave-one-out CV — honest for small N.
    preds = np.empty(n)
    for k in range(n):
        mask = np.ones(n, dtype=bool)
        mask[k] = False
        pipe = Pipeline([("scaler", StandardScaler()), ("ridge", Ridge(alpha=1.0))])
        pipe.fit(X[mask], y[mask])
        preds[k] = pipe.predict(X[k : k + 1])[0]

    errors = preds - y
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    ss_res = float(np.sum(errors ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

    # Baseline: predict the training mean each fold (skill reference).
    base_preds = np.empty(n)
    for k in range(n):
        mask = np.ones(n, dtype=bool)
        mask[k] = False
        base_preds[k] = y[mask].mean()
    base_mae = float(np.mean(np.abs(base_preds - y)))

    result.update({
        "status": "ok",
        "loo_mae_weeks": round(mae, 2),
        "loo_rmse_weeks": round(rmse, 2),
        "loo_r2": round(r2, 3),
        "baseline_mean_mae_weeks": round(base_mae, 2),
        "skill_vs_baseline": round(1.0 - mae / base_mae, 3) if base_mae > 0 else None,
    })
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = run_backtest()
    logger.info("Aggregate lead-time backtest (SFG target, lagged GSCPI/IPG features):")
    for k, v in res.items():
        logger.info("  %-24s %s", k, v)


if __name__ == "__main__":
    main()
