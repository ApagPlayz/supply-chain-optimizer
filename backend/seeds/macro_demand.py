"""Shared constants + a VINTAGE-PINNED loader for the real macro demand series.

`seeds/run_forecast_backtest.py` and `seeds/run_chronos_benchmark.py` both score
models against Census M3 `A34SNO` — an actually-observed macro demand series, as
opposed to the retired `seeds/train_forecasts.py` per-part seed (deleted; its
demand magnitude was derived from inventory/risk, not observed). This module gives
those two backtests (plus their tests) one place to get the series id, the on-disk
pins, and the loader.

WHY THE VINTAGE PIN EXISTS (2026-08-16)
---------------------------------------
The previous loader refetched `A34SNO` live from FRED on every run and OVERWROTE
`seeds/data/a34sno_monthly.csv`. That "cache" was write-through, not a pin, so a
backtest was only ever reproducible on the day it was run. Census revises M3 in
place and FRED mirrors the revision, so the input silently changed underneath the
published headline. Two committed artifacts covering an *identical* 197-month
window disagreed for exactly this reason:

    docs/forecast_backtest.json   seasonal-naive WAPE 0.0438 / RMSE 1501.68
    docs/chronos_benchmark.json   seasonal-naive WAPE 0.0437 / RMSE 1500.20

Replayed against ALFRED, that is one revised observation:

    vintage 2026-07-01   2026-05 = 29906   -> naive WAPE 0.0438  (forecast_backtest)
    vintage 2026-07-10   2026-05 = 29883   -> naive WAPE 0.0437  (chronos_benchmark)
    vintage 2026-08-16   2026-05 = 30134, plus a new 2026-06 = 31105

The harness was innocent; the *data* moved. So the fix is to pin the vintage.

HOW THE PIN WORKS
-----------------
ALFRED (https://alfred.stlouisfed.org) serves historical vintages of FRED series
through a keyless CSV endpoint. Verified against the live service on 2026-08-16:
A34SNO vintages resolve correctly and the response renames the value column
`A34SNO_<YYYYMMDD>`, which the client checks so an ignored pin cannot pass as a
honoured one.

Each vintage is stored VERBATIM under `seeds/data/a34sno_vintages/` as an immutable,
committed file named for its vintage date. A pinned run reads that file and does no
network I/O at all. Nothing overwrites `a34sno_monthly.csv` any more unless a human
explicitly passes `--refresh-cache`.

CHOOSING THE PIN — the rule, stated before the answer
-----------------------------------------------------
`DEFAULT_VINTAGE` is *the most recent vintage available on the day of republication*.
It is chosen by DATE, not by which model it favours. `PUBLISHED_VINTAGE` records the
vintage the original (now-superseded) headline was computed on, so the sensitivity of
the result to the vintage can be shown rather than hidden.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from app.ml.backtest import Fold

logger = logging.getLogger(__name__)

# Census M3 "Manufacturers' New Orders: Computers & Electronic Products" ($M, monthly,
# 1992->now) — the real macro *demand* target, served keyless via the FRED CSV endpoint.
FRED_DEMAND_SERIES = "A34SNO"
SERIES_START = "2010-01-01"

DATA_DIR = Path(__file__).resolve().parent / "data"

# Legacy unpinned snapshot. Kept for offline fallback and for continuity, but NO
# LONGER WRITTEN on an ordinary run. Its bytes are byte-identical (in values) to
# ALFRED vintage 2026-07-10 — see PUBLISHED_VINTAGE.
CACHE_PATH = DATA_DIR / "a34sno_monthly.csv"

# Immutable, committed vintage pins. One file per vintage date, stored verbatim as
# ALFRED served it (so the value-column name carries the vintage).
VINTAGE_DIR = DATA_DIR / "a34sno_vintages"

# The pin every published artifact is now built on: the latest vintage available on
# the day of republication (2026-08-16). Chosen by date, not by outcome.
DEFAULT_VINTAGE = "2026-08-16"

# The vintage the ORIGINAL published headline was computed on. Retained so the
# vintage-sensitivity of the result can be reported instead of buried.
PUBLISHED_VINTAGE = "2026-07-10"

# SHA-256 of the committed unpinned snapshot, recorded so the offline fallback can
# say whether it is serving the bytes this repo was published against.
COMMITTED_CACHE_SHA256 = "4a1f863b76d0d0c80e4c47c41e82863ee71d110d46bdc5c13f1e18471c2f720a"

# SHA-256 of each committed vintage pin, so a test can prove the pins have not been
# edited and a reader can verify them against ALFRED independently.
VINTAGE_SHA256: dict[str, str] = {
    # Real-time origin vintages (one per rolling origin — see REALTIME_ORIGIN_VINTAGES).
    "2023-08-01": "12b36a8092125a78f124851edfbcf314ada890c90ba4272a6705b29a96c002e6",
    "2024-08-01": "e039ea94a479895a70d79cd97876955a4937c871cf946e653155516717e21bb0",
    "2025-08-01": "d7c5a6788d5a529e9d7e715ae93c3ad82229b458cffa194ab455c6eb59efd8fb",
    # Publication/reference vintages.
    "2026-07-01": "a44b9a328c8762f04b9d9a95d427099b2aadbf39dfeffe18bcbb71ca76e15469",
    "2026-07-10": "d1d62c69a0be62d885cdb298815c3794bb397eb12687cc256bc33783cc17b7c0",
    "2026-08-16": "b5e61299781f39eae5b4c6bf041ed58a9e29afb708bda61e9024212b8619b557",
}


# ── True real-time protocol ──────────────────────────────────────────────────
#
# A pseudo-real-time backtest (slice the latest, fully revised series) hands every
# origin data that did not exist yet at that origin. That is a leakage class distinct
# from the usual ML ones, and on a revised series it is not small. The real-time
# protocol instead gives each origin ONLY the vintage that actually existed then.
#
# Census M3 publishes month M roughly six weeks later, so the vintage dated the 1st of
# August in year Y contains observations through June of year Y. Verified against
# ALFRED on 2026-08-16:
#
#     vintage 2023-08-01 -> 162 obs, ends 2023-06-01
#     vintage 2024-08-01 -> 174 obs, ends 2024-06-01
#     vintage 2025-08-01 -> 186 obs, ends 2025-06-01
#
# Those are EXACTLY the training sizes the pseudo-real-time rolling origins produce on
# the 2026-08-16 reference vintage ([162, 174, 186]). That coincidence is what makes
# the two protocols directly comparable: same origins, same training lengths, same
# target months, same actuals. The ONLY difference is whether the training values are
# the revised ones or the ones a forecaster could actually have seen.
REALTIME_ORIGIN_VINTAGES: tuple[str, ...] = ("2023-08-01", "2024-08-01", "2025-08-01")


def load_realtime_folds(
    reference_vintage: str = DEFAULT_VINTAGE,
    origin_vintages: Sequence[str] = REALTIME_ORIGIN_VINTAGES,
    horizon: int = 12,
    *,
    allow_network: bool = True,
) -> tuple[list["Fold"], dict[str, Any]]:
    """Build real-time backtest folds: train on the origin's vintage, score on the reference.

    Returns ``(folds, meta)``. Each fold trains on everything the origin vintage
    contained and is scored on the ``horizon`` months that follow, taken from the single
    ``reference_vintage`` so every model and every protocol is scored against identical
    targets.

    Raises RuntimeError if a target month is missing from the reference vintage, rather
    than silently shortening a fold.
    """
    from app.ml.backtest import Fold

    ref = load_demand_series(reference_vintage, allow_network=allow_network)
    ref_by_date = {str(d.date()): float(v) for d, v in ref.series.items()}

    folds: list[Fold] = []
    origins: list[dict[str, Any]] = []
    for vintage in origin_vintages:
        load = load_demand_series(vintage, allow_network=allow_network)
        train = [float(v) for v in load.series.to_numpy()]
        last = load.series.index.max()
        target_dates = [
            str((last.to_period("M") + step).to_timestamp().date())
            for step in range(1, horizon + 1)
        ]
        missing = [d for d in target_dates if d not in ref_by_date]
        if missing:
            raise RuntimeError(
                f"reference vintage {reference_vintage} is missing target months "
                f"{missing} for origin vintage {vintage} — cannot score this fold."
            )
        folds.append(
            Fold(
                train=train,
                actual=[ref_by_date[d] for d in target_dates],
                label=f"origin_vintage={vintage}",
            )
        )
        origins.append({
            "origin_vintage": vintage,
            "n_train": len(train),
            "train_ends": str(last.date()),
            "targets": [target_dates[0], target_dates[-1]],
            "values_sha256": load.values_sha256,
            "reproducible": load.reproducible,
        })

    meta = {
        "protocol": "real_time_vintage_per_origin",
        "reference_vintage": reference_vintage,
        "reference_values_sha256": ref.values_sha256,
        "actuals_source": (
            f"reference vintage {reference_vintage} (final/latest revised values). All "
            "models are scored against identical actuals, so the model comparison is "
            "unaffected by this choice; it only defines what 'the truth' means."
        ),
        "horizon": horizon,
        "origins": origins,
    }
    return folds, meta


def vintage_cache_path(vintage: str) -> Path:
    """Path of the immutable committed pin for a given vintage date."""
    return VINTAGE_DIR / f"{FRED_DEMAND_SERIES.lower()}_{vintage.replace('-', '')}.csv"


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical_values_sha256(series: "pd.Series") -> str:
    """Hash the OBSERVATIONS, independent of CSV header naming.

    Two ALFRED vintages can differ in bytes (the value column is named for the
    vintage) while carrying identical data — 2026-07-10 and 2026-07-13 do exactly
    that. This hash is what actually determines a backtest result, so it is the one
    worth comparing across artifacts.
    """
    lines = [f"{d.date()},{float(v):.6g}" for d, v in series.items()]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass
class SeriesLoad:
    """A loaded demand series plus everything needed to reproduce it."""

    series: "pd.Series"
    vintage: Optional[str]
    source: str
    path: Optional[Path]
    file_sha256: Optional[str]
    values_sha256: str
    reproducible: bool
    warnings: list[str] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        """The provenance block every artifact built from this series must carry."""
        return {
            "series_id": FRED_DEMAND_SERIES,
            "vintage": self.vintage,
            "vintage_source": self.source,
            "vintage_file": (
                str(self.path.relative_to(Path(__file__).resolve().parents[2]))
                if self.path
                else None
            ),
            "vintage_file_sha256": self.file_sha256,
            "series_values_sha256": self.values_sha256,
            "reproducible": self.reproducible,
            "n_obs": int(len(self.series)),
            "start": str(self.series.index.min().date()),
            "end": str(self.series.index.max().date()),
            "warnings": list(self.warnings),
        }


def _parse(raw: str) -> "pd.Series":
    from app.ml.fred_client import parse_fred_csv

    return parse_fred_csv(raw, FRED_DEMAND_SERIES).rename(FRED_DEMAND_SERIES)


def load_demand_series(
    as_of: Optional[str] = DEFAULT_VINTAGE,
    *,
    refresh_pin: bool = False,
    allow_network: bool = True,
) -> SeriesLoad:
    """Load `A34SNO` at a pinned vintage.

    ``as_of``  — ``YYYY-MM-DD`` vintage date, or ``None`` for the latest (NOT
                 reproducible; the returned load is flagged as such).
    ``refresh_pin`` — re-download a pin that already exists on disk and verify it
                 still matches. ALFRED vintages are immutable, so a mismatch is a
                 real finding and is reported loudly rather than written over.
    ``allow_network`` — set False to force a purely offline, committed-bytes run.
    """
    warnings: list[str] = []

    # ── Unpinned latest ─────────────────────────────────────────────────────
    if as_of is None:
        from app.ml.fred_client import fetch_fred_series_csv

        series = fetch_fred_series_csv(FRED_DEMAND_SERIES, start=SERIES_START)
        if series is None:
            raise RuntimeError(
                "--latest requested but the live FRED fetch failed. "
                "Re-run with a pinned --as-of vintage instead."
            )
        warnings.append(
            "UNPINNED RUN: this series is the latest FRED vintage. Census revises "
            "M3 in place, so these numbers are NOT reproducible on a later date. "
            "Do not publish them without a vintage pin."
        )
        return SeriesLoad(
            series=series,
            vintage=None,
            source="fred_latest_live",
            path=None,
            file_sha256=None,
            values_sha256=canonical_values_sha256(series),
            reproducible=False,
            warnings=warnings,
        )

    # ── Pinned vintage: committed file first, no network needed ─────────────
    pin = vintage_cache_path(as_of)
    if pin.is_file() and not refresh_pin:
        raw = pin.read_bytes()
        series = _parse(raw.decode("utf-8"))
        return SeriesLoad(
            series=series,
            vintage=as_of,
            source="alfred_vintage_pin_committed",
            path=pin,
            file_sha256=_sha256_bytes(raw),
            values_sha256=canonical_values_sha256(series),
            reproducible=True,
            warnings=warnings,
        )

    # ── Pinned vintage: fetch it from ALFRED and commit the pin ─────────────
    if allow_network:
        fetched = _download_vintage(as_of)
        if fetched is not None:
            raw_text, series = fetched
            if pin.is_file():
                existing = pin.read_bytes()
                if existing != raw_text.encode("utf-8"):
                    msg = (
                        f"ALFRED vintage {as_of} no longer matches the committed pin "
                        f"{pin.name}. ALFRED vintages are supposed to be immutable — "
                        "keeping the committed bytes and NOT overwriting them."
                    )
                    logger.error(msg)
                    warnings.append(msg)
                    series = _parse(existing.decode("utf-8"))
                    raw_text = existing.decode("utf-8")
            else:
                VINTAGE_DIR.mkdir(parents=True, exist_ok=True)
                pin.write_text(raw_text)
                logger.info("Pinned ALFRED vintage %s -> %s", as_of, pin)
            return SeriesLoad(
                series=series,
                vintage=as_of,
                source="alfred_vintage_pin_fetched",
                path=pin,
                file_sha256=_sha256_bytes(raw_text.encode("utf-8")),
                values_sha256=canonical_values_sha256(series),
                reproducible=True,
                warnings=warnings,
            )

    # ── Offline fallback: the committed unpinned snapshot, hash-checked ─────
    if not CACHE_PATH.is_file():
        raise RuntimeError(
            f"No pin for vintage {as_of} at {pin}, ALFRED unreachable, and no "
            f"committed snapshot at {CACHE_PATH}. Cannot run a backtest."
        )
    raw = CACHE_PATH.read_bytes()
    digest = _sha256_bytes(raw)
    series = _parse(raw.decode("utf-8"))
    matches = digest == COMMITTED_CACHE_SHA256
    warnings.append(
        f"FALLBACK: vintage {as_of} could not be pinned from ALFRED. Using the "
        f"committed snapshot {CACHE_PATH.name} (sha256 {digest[:16]}…), which "
        + (
            f"matches the recorded hash and equals ALFRED vintage {PUBLISHED_VINTAGE}."
            if matches
            else "DOES NOT match the recorded hash — the snapshot has been modified."
        )
    )
    for w in warnings:
        logger.warning(w)
    return SeriesLoad(
        series=series,
        vintage=PUBLISHED_VINTAGE if matches else None,
        source="committed_snapshot_fallback",
        path=CACHE_PATH,
        file_sha256=digest,
        values_sha256=canonical_values_sha256(series),
        reproducible=matches,
        warnings=warnings,
    )


def _download_vintage(as_of: str) -> Optional[tuple[str, "pd.Series"]]:
    """Fetch one ALFRED vintage verbatim. Returns (raw_csv_text, series) or None."""
    import urllib.request

    from app.ml.fred_client import ALFREDGRAPH_CSV_URL

    url = (
        f"{ALFREDGRAPH_CSV_URL}?id={FRED_DEMAND_SERIES}"
        f"&vintage_date={as_of}&cosd={SERIES_START}"
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed gov host)
            raw = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - offline is an expected path
        logger.warning("ALFRED vintage fetch failed for %s @ %s: %s", FRED_DEMAND_SERIES, as_of, exc)
        return None

    from app.ml.fred_client import _csv_value_column

    expected = f"{FRED_DEMAND_SERIES}_{as_of.replace('-', '')}"
    if _csv_value_column(raw) != expected:
        logger.error(
            "ALFRED did not honour vintage %s (value column %r, expected %r) — refusing it.",
            as_of, _csv_value_column(raw), expected,
        )
        return None
    series = _parse(raw)
    if series.empty:
        logger.error("ALFRED vintage %s parsed to an empty series", as_of)
        return None
    return raw, series
