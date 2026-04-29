"""Forecast API endpoint tests (05-03, FORE-03).

Covers:
  - compute_weeks_until_stockout: zero-demand / zero-stock / normal / negative-clipping cases.
  - GET /forecasts/all: response shape, component grouping, empty-DB returns [].
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.models.component import Component, DistributorOffer
from app.models.forecast import ComponentForecast
from app.api.forecasts import compute_weeks_until_stockout


# ── Stock-out formula unit tests ─────────────────────────────────────────────

def test_stockout_zero_demand_returns_none():
    assert compute_weeks_until_stockout(total_stock=100, last_4_forecasts=[0.0, 0.0, 0.0, 0.0]) is None


def test_stockout_zero_stock_with_demand_returns_zero():
    assert compute_weeks_until_stockout(total_stock=0, last_4_forecasts=[5.0, 5.0, 5.0, 5.0]) == 0.0


def test_stockout_normal_case():
    # 100 stock / mean([10,10,10,10]) = 10 weeks
    assert compute_weeks_until_stockout(total_stock=100, last_4_forecasts=[10.0, 10.0, 10.0, 10.0]) == 10.0


def test_stockout_clips_negative_yhat():
    # mean of clipped [0, 0, 5, 5] = 2.5 -> 25 / 2.5 = 10 weeks
    assert compute_weeks_until_stockout(total_stock=25, last_4_forecasts=[-5.0, -1.0, 5.0, 5.0]) == 10.0


def test_stockout_empty_list_returns_none():
    assert compute_weeks_until_stockout(total_stock=100, last_4_forecasts=[]) is None


# ── Endpoint integration tests ───────────────────────────────────────────────

@pytest.fixture
def forecast_db(tmp_path):
    """3-component DB with 12 forecast rows each + 2 distributor offers."""
    db_url = f"sqlite:///{tmp_path / 'forecast_api.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    base_date = datetime(2026, 5, 4, tzinfo=timezone.utc)

    # Component 1: stock=100, forecast=10/wk -> 10 weeks until stockout
    # Component 2: stock=1000, forecast=5/wk -> 200 weeks (>12 -> no badge)
    # Component 3: stock=0, forecast=5/wk -> 0 weeks (out of stock)
    for comp_id, stock, weekly_demand in [(1, 100, 10.0), (2, 1000, 5.0), (3, 0, 5.0)]:
        session.add(Component(
            id=comp_id, mpn=f"PART-{comp_id}", manufacturer="TestCo",
            category="Microcontrollers", risk_score=0.2,
        ))
        session.add(DistributorOffer(
            id=comp_id, component_id=comp_id, distributor_id=1,
            price=1.0, stock=stock, sku=f"SKU-{comp_id}", currency="USD", moq=1,
        ))
        for wk in range(12):
            session.add(ComponentForecast(
                component_id=comp_id,
                forecast_date=base_date + timedelta(weeks=wk),
                predicted_demand=weekly_demand,
                lower_bound=weekly_demand * 0.8,
                upper_bound=weekly_demand * 1.2,
            ))
    session.commit()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    yield session
    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_forecasts_all_endpoint_returns_data(forecast_db):
    client = TestClient(app)
    res = client.get("/api/v1/forecasts/all")
    assert res.status_code == 200, res.text
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 3
    component_ids = sorted(row["component_id"] for row in data)
    assert component_ids == [1, 2, 3]


def test_forecasts_all_endpoint_returns_12_points_each(forecast_db):
    client = TestClient(app)
    res = client.get("/api/v1/forecasts/all")
    data = res.json()
    for row in data:
        assert len(row["forecast_points"]) == 12, row
        for p in row["forecast_points"]:
            assert "forecast_date" in p
            assert "predicted_demand" in p
            assert p["predicted_demand"] == 10.0 or p["predicted_demand"] == 5.0
            assert p["lower_bound"] is not None
            assert p["upper_bound"] is not None


def test_forecasts_all_endpoint_stockout_values(forecast_db):
    client = TestClient(app)
    res = client.get("/api/v1/forecasts/all")
    data = {row["component_id"]: row["weeks_until_stockout"] for row in res.json()}
    assert data[1] == 10.0     # 100 / 10 = 10 weeks
    assert data[2] == 200.0    # 1000 / 5 = 200 weeks (frontend will hide >12)
    assert data[3] == 0.0      # 0 stock, positive demand -> already out


def test_forecasts_all_endpoint_empty_db(client):
    """Empty DB returns [] (200) — does not raise."""
    res = client.get("/api/v1/forecasts/all")
    assert res.status_code == 200
    assert res.json() == []


def test_forecasts_all_endpoint_is_public(forecast_db):
    """Matches benchmark API pattern: no auth required."""
    client = TestClient(app)
    res = client.get("/api/v1/forecasts/all")  # no Authorization header
    assert res.status_code == 200, res.text
