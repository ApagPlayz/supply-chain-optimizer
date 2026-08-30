"""Tests for FRED feature engineering (no live API calls)."""
import numpy as np
import pandas as pd
import pytest

import app.ml.fred_client as fred_client
from app.ml.fred_client import (
    engineer_features,
    compute_stress_label,
    FRED_SERIES,
    parse_fred_csv,
    build_weekly_demand_shape,
)


def _make_fake_df() -> pd.DataFrame:
    """Build a minimal monthly DataFrame mimicking FRED output."""
    idx = pd.date_range("2020-01-01", periods=36, freq="MS")
    data = {
        "ppi_semis":       [100 + i * 0.5 for i in range(36)],
        "capacity_util":   [70 + (1 if i >= 18 else 0) * 6 for i in range(36)],
        "inventory_ratio": [1.40 - (0.1 if i >= 18 else 0) for i in range(36)],
        "industrial_prod": [150 + i * 0.3 for i in range(36)],
        "import_price":    [80 + i * 0.2 for i in range(36)],
        "freight_tsi":     [120 + i * 0.1 for i in range(36)],
    }
    return pd.DataFrame(data, index=idx)


def test_engineer_features_shape():
    df = _make_fake_df()
    features = engineer_features(df)
    # 6 series × 3 features = 18 columns
    assert features.shape[1] == 18


def test_engineer_features_no_nan():
    df = _make_fake_df()
    features = engineer_features(df)
    assert not features.isnull().any().any()


def test_engineer_features_column_names():
    df = _make_fake_df()
    features = engineer_features(df)
    for series_name in FRED_SERIES.keys():
        assert f"{series_name}_level" in features.columns
        assert f"{series_name}_mom3" in features.columns
        assert f"{series_name}_z12" in features.columns


def test_compute_stress_label_fires_on_threshold():
    df = _make_fake_df()
    # Months 18+ have capacity_util=76 and inventory_ratio=1.30 → stress=1
    labels = compute_stress_label(df)
    assert labels.iloc[:18].sum() == 0   # no stress in first 18 months
    assert labels.iloc[18:].sum() == 18  # all 18 remaining months are stress


def test_compute_stress_label_shape():
    df = _make_fake_df()
    labels = compute_stress_label(df)
    assert len(labels) == len(df)


# ── Keyless CSV parsing + demand-shape builder (no network) ──────────────────

def test_parse_fred_csv_basic():
    raw = (
        "observation_date,IPG3344S\n"
        "2020-01-01,100.0\n"
        "2020-02-01,101.5\n"
        "2020-03-01,99.2\n"
    )
    s = parse_fred_csv(raw, "IPG3344S")
    assert list(s.values) == [100.0, 101.5, 99.2]
    assert str(s.index[0].date()) == "2020-01-01"


def test_parse_fred_csv_drops_missing_marker():
    """FRED encodes missing observations as '.', which must become dropped NaN."""
    raw = "observation_date,IPG3344S\n2020-01-01,100.0\n2020-02-01,.\n2020-03-01,102.0\n"
    s = parse_fred_csv(raw, "IPG3344S")
    assert len(s) == 2
    assert list(s.values) == [100.0, 102.0]


def test_build_weekly_demand_shape_is_unit_mean():
    idx = pd.date_range("2022-01-01", periods=24, freq="MS")
    monthly = pd.Series(np.linspace(80, 120, 24), index=idx, name="IPG3344S")
    shape = build_weekly_demand_shape(monthly, weeks=52)
    assert shape.shape == (52,)
    assert abs(float(np.mean(shape)) - 1.0) < 1e-9
    assert (shape > 0).all()


def test_build_weekly_demand_shape_rejects_empty():
    with pytest.raises(ValueError):
        build_weekly_demand_shape(pd.Series([], dtype=float), weeks=52)


# ═══════════════════════════════════════════════════════════════════════════
# The committed seed CSVs are READ-ONLY unless a retrain deliberately says so
# ═══════════════════════════════════════════════════════════════════════════
#
# THE DEFECT. `fetch_gscpi()` and `fetch_regime_feature_frame()` used to write
# `seeds/data/gscpi_monthly.csv` and `seeds/data/regime_features_monthly.csv`
# on EVERY successful download — a write-on-read. Both use keyless endpoints, so
# no API key gated them, and both are reached from `build_regime_dataset()`,
# which two `@pytest.mark.integration` tests in test_regime_model.py call. Running
# the documented gate `pytest tests/ -q` could therefore silently replace a
# committed seed CSV with a fresh, unpinned vintage. Commit 035ae78 (a lead-time
# fix) rewrote 685 lines of gscpi_monthly.csv exactly this way.
#
# GSCPI is revised IN PLACE by the NY Fed with no archival endpoint, so such an
# overwrite is irreversible: the vintage the shipped model was trained on is gone.
#
# These tests pin the guard from both sides — a read must NOT write, and the
# deliberate retrain path MUST still be able to. Every seeds/data path is
# redirected to tmp_path first, so a regression here dirties a temp dir rather
# than the repo.

@pytest.fixture
def isolated_seed_cache(tmp_path, monkeypatch):
    """Redirect every seeds/data write to tmp_path for the duration of a test."""
    monkeypatch.setattr(fred_client, "SEED_DATA_DIR", tmp_path)
    monkeypatch.setattr(fred_client, "GSCPI_CACHE", tmp_path / "gscpi_monthly.csv")
    monkeypatch.setattr(
        fred_client, "REGIME_FEATURE_CACHE", tmp_path / "regime_features_monthly.csv"
    )
    return tmp_path


def _fake_fred_series(series_id, start="1997-01-01", timeout=30, vintage_date=None):
    idx = pd.date_range("2000-01-01", periods=24, freq="MS")
    return pd.Series(np.linspace(1.0, 2.0, 24), index=idx, name=series_id)


class _FakeResponse:
    """Minimal stand-in for the urlopen context manager (no network in tests)."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_gscpi_download(monkeypatch):
    """Make fetch_gscpi's download succeed without touching the network."""
    monkeypatch.setattr(
        fred_client.urllib.request, "urlopen",
        lambda *a, **k: _FakeResponse(b"not-really-an-xls"),
    )
    frame = pd.DataFrame({
        "date": pd.date_range("2000-01-01", periods=24, freq="MS"),
        "gscpi": np.linspace(-1.0, 1.0, 24),
    })
    monkeypatch.setattr(fred_client.pd, "read_excel", lambda *a, **k: frame)


def test_reading_regime_features_does_not_write_the_committed_cache(
    isolated_seed_cache, monkeypatch
):
    """A plain read must leave seeds/data/regime_features_monthly.csv alone."""
    monkeypatch.setattr(fred_client, "fetch_fred_series_csv", _fake_fred_series)

    df = fred_client.fetch_regime_feature_frame()

    assert df is not None and not df.empty, "the fixture must produce a real frame"
    assert not fred_client.REGIME_FEATURE_CACHE.exists(), (
        "fetch_regime_feature_frame() wrote the committed seed CSV on a plain read. "
        "That is the write-on-read defect: `pytest tests/` would mutate "
        "backend/seeds/data/ with an unpinned vintage."
    )


def test_a_deliberate_refresh_still_writes_the_regime_feature_cache(
    isolated_seed_cache, monkeypatch
):
    """The retrain path must keep working — the guard is opt-in, not a removal."""
    monkeypatch.setattr(fred_client, "fetch_fred_series_csv", _fake_fred_series)

    df = fred_client.fetch_regime_feature_frame(refresh_cache=True)

    assert df is not None
    assert fred_client.REGIME_FEATURE_CACHE.exists(), (
        "refresh_cache=True must still refresh the cache, or a retrain can no "
        "longer update the committed features at all"
    )
    written = pd.read_csv(fred_client.REGIME_FEATURE_CACHE)
    assert len(written) == len(df)


def test_reading_gscpi_does_not_write_the_committed_cache(
    isolated_seed_cache, monkeypatch
):
    """GSCPI is revision-in-place: an accidental overwrite is unrecoverable."""
    _fake_gscpi_download(monkeypatch)

    series = fred_client.fetch_gscpi()

    assert series is not None and not series.empty
    assert not fred_client.GSCPI_CACHE.exists(), (
        "fetch_gscpi() overwrote the committed seed CSV on a plain read. GSCPI has "
        "no vintage endpoint, so the superseded vintage cannot be recovered."
    )


def test_a_deliberate_refresh_still_writes_the_gscpi_cache(
    isolated_seed_cache, monkeypatch
):
    _fake_gscpi_download(monkeypatch)

    series = fred_client.fetch_gscpi(refresh_cache=True)

    assert series is not None
    assert fred_client.GSCPI_CACHE.exists(), (
        "refresh_cache=True must still refresh the GSCPI cache"
    )


def test_a_vintage_pin_reaches_every_regime_feature_request(
    isolated_seed_cache, monkeypatch
):
    """fetch_regime_feature_frame ignored vintage_date entirely, so a retrain
    could not be pinned even though fetch_fred_series_csv supports ALFRED."""
    seen: list[tuple[str, object]] = []

    def spy(series_id, start="1997-01-01", timeout=30, vintage_date=None):
        seen.append((series_id, vintage_date))
        return _fake_fred_series(series_id)

    monkeypatch.setattr(fred_client, "fetch_fred_series_csv", spy)

    fred_client.fetch_regime_feature_frame(vintage_date="2026-08-01")
    assert len(seen) == len(fred_client.REGIME_FEATURE_SERIES)
    assert {v for _, v in seen} == {"2026-08-01"}, (
        "the vintage pin never reached fetch_fred_series_csv, so the ALFRED "
        "endpoint was never used and the retrain is not reproducible"
    )

    # ...and the default must stay unpinned (latest vintage) — unchanged behaviour.
    seen.clear()
    fred_client.fetch_regime_feature_frame()
    assert {v for _, v in seen} == {None}
