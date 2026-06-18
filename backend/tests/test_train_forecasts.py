"""Unit + integration tests for seeds.train_forecasts (FORE-02).

Strategy:
  - Unit tests on generate_demand_series: shape, non-negativity, reproducibility,
    risk-score sensitivity, zero-stock floor.
  - Integration smoke test: run main() against a 5-component in-memory DB,
    verify 5*52 history rows and 5*12 forecast rows are written, verify yhat_lower
    and yhat_upper are populated (Pitfall 2 regression guard).

The full 791-component run is verified via the manual command in 05-VALIDATION.md
and by /gsd-verify-work — not in the unit test suite (Prophet ~1.2 min runtime).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import numpy as np
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.component import Component, DistributorOffer
from app.models.forecast import ComponentDemandHistory, ComponentForecast


# ── Unit tests on generate_demand_series ─────────────────────────────────────
# generate_demand_series is now driven by a real unit-mean FRED index shape
# (no np.random). FLAT_SHAPE = a constant unit-mean shape isolates the
# scaling/risk logic; WAVE_SHAPE exercises the temporal modulation.
FLAT_SHAPE = np.ones(52)
WAVE_SHAPE = (1.0 + 0.2 * np.sin(np.linspace(0, 2 * np.pi, 52)))  # mean ≈ 1.0, varies ±20%


def test_generate_demand_series_shape():
    from seeds.train_forecasts import generate_demand_series
    series = generate_demand_series(total_stock=1000, risk_score=0.3, index_shape=FLAT_SHAPE)
    assert len(series) == 52
    assert all(v >= 0.0 for v in series)


def test_generate_demand_series_deterministic():
    """Same inputs => same output (no RNG — fully real-data-driven)."""
    from seeds.train_forecasts import generate_demand_series
    a = generate_demand_series(500, 0.4, index_shape=WAVE_SHAPE)
    b = generate_demand_series(500, 0.4, index_shape=WAVE_SHAPE)
    assert (a == b).all()


def test_generate_demand_series_follows_index_shape():
    """The series must track the real index trajectory, not be flat/random."""
    from seeds.train_forecasts import generate_demand_series
    series = generate_demand_series(1000, 0.3, index_shape=WAVE_SHAPE)
    # peak/trough of the demand line up with the index shape's peak/trough
    assert int(np.argmax(series)) == int(np.argmax(WAVE_SHAPE))
    assert int(np.argmin(series)) == int(np.argmin(WAVE_SHAPE))
    # and a flat shape yields a flat series
    flat = generate_demand_series(1000, 0.3, index_shape=FLAT_SHAPE)
    assert np.allclose(flat, flat[0])


def test_generate_demand_series_wrong_length_raises():
    from seeds.train_forecasts import generate_demand_series
    with pytest.raises(ValueError):
        generate_demand_series(1000, 0.3, index_shape=np.ones(10))


def test_generate_demand_series_zero_stock_floor():
    """RESEARCH.md Pitfall 4: stock=0 must NOT produce all-zero series."""
    from seeds.train_forecasts import generate_demand_series
    series = generate_demand_series(total_stock=0, risk_score=0.166, index_shape=FLAT_SHAPE)
    assert len(series) == 52
    # base_rate floored at 1.0 — average should be at least 0.5/week
    assert sum(series) / len(series) >= 0.5


def test_generate_demand_series_risk_sensitivity():
    """RESEARCH.md Pitfall 3: high-risk demand meaningfully exceeds zero-risk."""
    from seeds.train_forecasts import generate_demand_series
    high = generate_demand_series(total_stock=1000, risk_score=0.700, index_shape=FLAT_SHAPE)
    low = generate_demand_series(total_stock=1000, risk_score=0.000, index_shape=FLAT_SHAPE)
    # max risk should produce ~5x the cumulative demand of zero risk
    assert sum(high) > sum(low) * 1.5, (sum(high), sum(low))


def test_generate_demand_series_risk_multiplier_capped():
    """Even at risk_score=1.0 (above observed 0.700 max), multiplier caps at 5.0."""
    from seeds.train_forecasts import generate_demand_series
    capped = generate_demand_series(total_stock=1000, risk_score=1.0, index_shape=FLAT_SHAPE)
    very_high = generate_demand_series(total_stock=1000, risk_score=0.83, index_shape=FLAT_SHAPE)
    # 1.0 -> multiplier = min(1 + 1/0.166, 5) = min(7, 5) = 5.0 (CAPPED)
    # 0.83 -> multiplier = min(1 + 0.83/0.166, 5) = min(6, 5) = 5.0 (also capped)
    # so the two should produce the same series
    assert (capped == very_high).all()


# ── Integration smoke test on main() ─────────────────────────────────────────

@pytest.fixture
def small_forecast_db(tmp_path):
    """5-component in-memory DB for fast pipeline smoke."""
    db_url = f"sqlite:///{tmp_path / 'forecast_smoke.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    for i in range(1, 6):
        risk = 0.1 * i  # 0.1, 0.2, 0.3, 0.4, 0.5
        session.add(Component(
            id=i, mpn=f"PART-{i}", manufacturer="TestCo",
            category="Microcontrollers", risk_score=risk,
        ))
        session.add(DistributorOffer(
            id=i, component_id=i, distributor_id=1,
            price=1.0, stock=100 if i != 3 else 0,   # comp 3 is zero-stock (covers Pitfall 4)
            sku=f"SKU-{i}", currency="USD", moq=1,
        ))
    session.commit()
    session.close()

    yield engine
    Base.metadata.drop_all(bind=engine)


def test_main_writes_correct_row_counts(small_forecast_db):
    """Integration: main() writes 5*52=260 history rows and 5*12=60 forecast rows."""
    # Patch the `engine` symbol that train_forecasts imports from app.core.database
    # so the script writes to the test DB, not the real supply_chain.db.
    # Patch the FRED shape loader to a fixed unit-mean shape — keeps the smoke test
    # offline/fast (the real fetch is exercised by test_fred_client).
    with patch("app.core.database.engine", small_forecast_db), \
         patch("seeds.train_forecasts.load_demand_index_shape", return_value=FLAT_SHAPE):
        from seeds import train_forecasts
        # Re-import inside the patch so the module re-binds the engine reference at main() runtime.
        # main() does `from app.core.database import engine` lazily, so the patch is effective.
        train_forecasts.main()

    Session = sessionmaker(bind=small_forecast_db)
    session = Session()
    try:
        n_hist = session.query(ComponentDemandHistory).count()
        n_fcst = session.query(ComponentForecast).count()
        assert n_hist == 5 * 52, f"expected 260 history rows, got {n_hist}"
        assert n_fcst == 5 * 12, f"expected 60 forecast rows, got {n_fcst}"
    finally:
        session.close()


def test_main_writes_uncertainty_bounds(small_forecast_db):
    """Pitfall 2 regression: yhat_lower / yhat_upper must be populated, not NULL."""
    with patch("app.core.database.engine", small_forecast_db), \
         patch("seeds.train_forecasts.load_demand_index_shape", return_value=FLAT_SHAPE):
        from seeds import train_forecasts
        train_forecasts.main()

    Session = sessionmaker(bind=small_forecast_db)
    session = Session()
    try:
        forecasts = session.query(ComponentForecast).all()
        assert len(forecasts) > 0
        with_lower = sum(1 for f in forecasts if f.lower_bound is not None)
        with_upper = sum(1 for f in forecasts if f.upper_bound is not None)
        # uncertainty_samples=100 produces yhat_lower/yhat_upper for every row
        assert with_lower == len(forecasts), f"only {with_lower}/{len(forecasts)} have lower_bound (Pitfall 2)"
        assert with_upper == len(forecasts), f"only {with_upper}/{len(forecasts)} have upper_bound (Pitfall 2)"
    finally:
        session.close()


def test_main_is_idempotent(small_forecast_db):
    """Pitfall 5 regression: running main() twice yields the same row counts (truncate-on-start)."""
    with patch("app.core.database.engine", small_forecast_db), \
         patch("seeds.train_forecasts.load_demand_index_shape", return_value=FLAT_SHAPE):
        from seeds import train_forecasts
        train_forecasts.main()
        train_forecasts.main()  # second run

    Session = sessionmaker(bind=small_forecast_db)
    session = Session()
    try:
        n_hist = session.query(ComponentDemandHistory).count()
        n_fcst = session.query(ComponentForecast).count()
        assert n_hist == 5 * 52, f"after re-run, expected 260 history rows, got {n_hist}"
        assert n_fcst == 5 * 12, f"after re-run, expected 60 forecast rows, got {n_fcst}"
    finally:
        session.close()
