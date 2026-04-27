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

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.component import Component, DistributorOffer
from app.models.forecast import ComponentDemandHistory, ComponentForecast


# ── Unit tests on generate_demand_series ─────────────────────────────────────

def test_generate_demand_series_shape():
    from seeds.train_forecasts import generate_demand_series
    series = generate_demand_series(total_stock=1000, risk_score=0.3, seed=42)
    assert len(series) == 52
    assert all(v >= 0.0 for v in series)


def test_generate_demand_series_reproducible():
    """Same inputs => same output (seed-based RNG)."""
    from seeds.train_forecasts import generate_demand_series
    a = generate_demand_series(500, 0.4, seed=123)
    b = generate_demand_series(500, 0.4, seed=123)
    assert (a == b).all()


def test_generate_demand_series_zero_stock_floor():
    """RESEARCH.md Pitfall 4: stock=0 must NOT produce all-zero series."""
    from seeds.train_forecasts import generate_demand_series
    series = generate_demand_series(total_stock=0, risk_score=0.166, seed=1)
    assert len(series) == 52
    # base_rate floored at 1.0 — average should be at least 0.5/week
    assert sum(series) / len(series) >= 0.5


def test_generate_demand_series_risk_sensitivity():
    """RESEARCH.md Pitfall 3: high-risk draws meaningfully faster than zero-risk."""
    from seeds.train_forecasts import generate_demand_series
    high = generate_demand_series(total_stock=1000, risk_score=0.700, seed=42)
    low = generate_demand_series(total_stock=1000, risk_score=0.000, seed=42)
    # max risk should produce ~5x the cumulative demand of zero risk
    assert sum(high) > sum(low) * 1.5, (sum(high), sum(low))


def test_generate_demand_series_risk_multiplier_capped():
    """Even at risk_score=1.0 (above observed 0.700 max), multiplier caps at 5.0."""
    from seeds.train_forecasts import generate_demand_series
    capped = generate_demand_series(total_stock=1000, risk_score=1.0, seed=42)
    very_high = generate_demand_series(total_stock=1000, risk_score=0.83, seed=42)
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
    with patch("app.core.database.engine", small_forecast_db):
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
    with patch("app.core.database.engine", small_forecast_db):
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
    with patch("app.core.database.engine", small_forecast_db):
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
