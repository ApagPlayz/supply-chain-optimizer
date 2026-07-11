"""Loader for the Monash Car Parts intermittent-demand dataset (REAL data).

The Monash Time Series Forecasting Archive publishes 2,674 real monthly car-parts
sales series (Jan 1998 - Mar 2002, 51 months each), extracted from the R
`expsmooth` package (Hyndman 2015). It is the canonical public benchmark for
*intermittent* demand — the exact pattern electronic-component / spare-part
planners face. No public per-SKU **electronic-component** demand series exists, so
this stands in as the real-data demonstration of the per-item technique.

Source: HuggingFace dataset `Monash-University/monash_tsf`, file
`data/car_parts_dataset_with_missing_values.zip` (CC-BY 4.0). Missing observations
(encoded `?` in the .tsf) are treated as 0 sales — this reproduces Monash's own
"without missing values" variant and is the standard convention for count data
where "no record" means "no sale that month".

Data is cached under seeds/data/ so the backtest is reproducible offline after the
first run.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)

HF_REPO = "Monash-University/monash_tsf"
HF_FILE = "data/car_parts_dataset_with_missing_values.zip"
SERIES_LENGTH = 51  # Jan 1998 -> Mar 2002, monthly
CACHE_PATH = Path(__file__).resolve().parent / "data" / "car_parts_monthly.npz"


def _parse_tsf(text: str) -> Dict[str, np.ndarray]:
    """Parse Monash .tsf text into {series_name: float array}. `?` -> 0.0."""
    series: Dict[str, np.ndarray] = {}
    in_data = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not in_data:
            if line.lower() == "@data":
                in_data = True
            continue
        # data row: "T1:1998-01-01 00-00-00:0,0,2,?,..."
        parts = line.split(":")
        name = parts[0]
        values_str = parts[-1]
        vals = [0.0 if v == "?" else float(v) for v in values_str.split(",")]
        series[name] = np.asarray(vals, dtype=float)
    return series


def load_car_parts(refresh: bool = True) -> Dict[str, np.ndarray]:
    """Return {series_name: float array} for all Monash car-parts SKUs.

    Resolution order (real-data-only — never fabricated):
      1. If refresh, download the .tsf zip from HuggingFace and refresh the cache.
      2. Otherwise / on failure, load the cached .npz snapshot in seeds/data/.
      3. If neither is available, raise.
    """
    series: Dict[str, np.ndarray] | None = None

    if refresh:
        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset")
            with zipfile.ZipFile(path) as zf:
                name = zf.namelist()[0]
                with zf.open(name) as fh:
                    text = fh.read().decode("utf-8", "replace")
            series = _parse_tsf(text)
            logger.info("Downloaded Monash car-parts (%d series) from HF", len(series))
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(
                    CACHE_PATH,
                    names=np.array(list(series.keys())),
                    values=np.stack(list(series.values())),
                )
            except Exception as exc:  # caching is best-effort
                logger.warning("could not cache car-parts data: %s", exc)
        except Exception as exc:
            logger.warning("HF download failed (%s) — falling back to cache", exc)
            series = None

    if series is None:
        if not CACHE_PATH.exists():
            raise FileNotFoundError(
                f"No Monash car-parts data: HF download failed and no cache at {CACHE_PATH}. "
                "Run once with network access to populate the cache."
            )
        blob = np.load(CACHE_PATH, allow_pickle=False)
        names, values = blob["names"], blob["values"]
        series = {str(n): values[i] for i, n in enumerate(names)}
        logger.info("Loaded Monash car-parts from cache (%d series)", len(series))

    return series


def as_matrix(series: Dict[str, np.ndarray]) -> tuple[List[str], np.ndarray]:
    """Return (names, N x T matrix) for series that all share SERIES_LENGTH."""
    names = [n for n, v in series.items() if len(v) == SERIES_LENGTH]
    mat = np.stack([series[n] for n in names])
    return names, mat


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = load_car_parts(refresh=True)
    names, mat = as_matrix(s)
    nz = (mat > 0).mean()
    logger.info(
        "car-parts: %d series x %d months | mean=%.3f | nonzero fraction=%.1f%%",
        mat.shape[0], mat.shape[1], mat.mean(), nz * 100,
    )
