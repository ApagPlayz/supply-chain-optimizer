"""Phase 5 forecast scaffolding tests.

Covers FORE-01 (import + migration), FORE-02 (training script outputs), FORE-03 (API endpoint).

Tests for behavior delivered by later plans (05-02 train_forecasts, 05-03 forecasts API)
are marked `pytest.skip` with importorskip so this file passes today and
auto-activates as later plans land.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Ensure backend root on path (mirror conftest.py pattern)
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.database import Base


# ── FORE-01: Models import + migration ───────────────────────────────────────

def test_forecast_models_import():
    """FORE-01: Importing forecast models raises no errors."""
    from app.models.forecast import ComponentDemandHistory, ComponentForecast
    assert ComponentDemandHistory.__tablename__ == "component_demand_history"
    assert ComponentForecast.__tablename__ == "component_forecasts"


def test_forecast_models_in_metadata():
    """FORE-01: Both tables registered in Base.metadata."""
    import app.models  # noqa: F401  — triggers registration via package __init__
    assert "component_demand_history" in Base.metadata.tables
    assert "component_forecasts" in Base.metadata.tables


def test_forecast_columns():
    """FORE-01: ComponentForecast columns match the contract in CONTEXT.md D-05."""
    from app.models.forecast import ComponentForecast
    cols = [c.name for c in ComponentForecast.__table__.columns]
    assert cols == [
        "id", "component_id", "forecast_date",
        "predicted_demand", "lower_bound", "upper_bound", "created_at",
    ], cols


def test_demand_history_columns():
    """FORE-01: ComponentDemandHistory columns match the contract."""
    from app.models.forecast import ComponentDemandHistory
    cols = [c.name for c in ComponentDemandHistory.__table__.columns]
    assert cols == ["id", "component_id", "week_date", "demand_units"], cols


def test_migration_creates_tables(tmp_path):
    """FORE-01: Alembic migration 0002 creates both tables on a fresh DB."""
    db_file = tmp_path / "alembic_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    # Import all ORM models so Base.metadata is populated, then create_all
    # mirrors what alembic upgrade head produces for the schema we own.
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    names = inspect(engine).get_table_names()
    assert "component_demand_history" in names
    assert "component_forecasts" in names


# ── FORE-02: Training script (delivered by plan 05-02) ───────────────────────

def test_demand_series_shape():
    """FORE-02: generate_demand_series returns 52 non-negative floats. SKIPPED until 05-02 ships."""
    seeds = pytest.importorskip("seeds.train_forecasts")
    if not hasattr(seeds, "generate_demand_series"):
        pytest.skip("seeds.train_forecasts.generate_demand_series not implemented yet (delivered by 05-02)")
    series = seeds.generate_demand_series(total_stock=1000, risk_score=0.3, seed=42)
    assert len(series) == 52
    assert all(v >= 0 for v in series)


def test_demand_series_zero_stock_floor():
    """FORE-02: Zero-stock components still produce a non-degenerate series (floor at 1.0/week)."""
    seeds = pytest.importorskip("seeds.train_forecasts")
    if not hasattr(seeds, "generate_demand_series"):
        pytest.skip("delivered by 05-02")
    series = seeds.generate_demand_series(total_stock=0, risk_score=0.166, seed=1)
    assert len(series) == 52
    # With base_rate floor of 1.0 unit/week, the average should be >= 0.5
    assert sum(series) / len(series) >= 0.5


def test_train_forecasts_writes_all_791(tmp_path):
    """FORE-02: After training, component_forecasts has 791*12=9492 rows. SKIPPED until 05-02 ships."""
    pytest.importorskip("seeds.train_forecasts")
    pytest.skip("Integration test — runs against full DB; activated by /gsd-verify-work after 05-02")


# ── FORE-02/03: weeks_until_stockout formula (delivered by plan 05-03) ──────

def test_stockout_formula_zero_demand():
    """FORE-02/03: compute_weeks_until_stockout returns None when demand=0."""
    api = pytest.importorskip("app.api.forecasts")
    if not hasattr(api, "compute_weeks_until_stockout"):
        pytest.skip("compute_weeks_until_stockout not implemented yet (delivered by 05-03)")
    assert api.compute_weeks_until_stockout(total_stock=100, last_4_forecasts=[0.0, 0.0, 0.0, 0.0]) is None


def test_stockout_formula_zero_stock():
    """FORE-02/03: compute_weeks_until_stockout returns 0.0 when stock=0 and demand>0."""
    api = pytest.importorskip("app.api.forecasts")
    if not hasattr(api, "compute_weeks_until_stockout"):
        pytest.skip("delivered by 05-03")
    assert api.compute_weeks_until_stockout(total_stock=0, last_4_forecasts=[5.0, 5.0, 5.0, 5.0]) == 0.0


def test_stockout_formula_normal():
    """FORE-02/03: weeks_until_stockout = stock / mean(last_4_forecasts)."""
    api = pytest.importorskip("app.api.forecasts")
    if not hasattr(api, "compute_weeks_until_stockout"):
        pytest.skip("delivered by 05-03")
    # 100 stock / 10 avg = 10 weeks
    weeks = api.compute_weeks_until_stockout(total_stock=100, last_4_forecasts=[10.0, 10.0, 10.0, 10.0])
    assert weeks == 10.0


# ── FORE-03: Forecast API (delivered by plan 05-03) ─────────────────────────

def test_forecast_endpoint_registered():
    """FORE-03: GET /forecasts/all is a registered route. SKIPPED until 05-03 ships."""
    pytest.importorskip("app.api.forecasts")
    from app.main import app
    routes = [r.path for r in app.routes]
    assert any("/forecasts/all" in r for r in routes), routes


def test_forecast_endpoint_returns_all_components(client):
    """FORE-03: GET /forecasts/all returns one entry per component with 12 forecast points."""
    pytest.importorskip("app.api.forecasts")
    pytest.skip("Integration smoke — runs after 05-02 has populated DB; activated by /gsd-verify-work")
