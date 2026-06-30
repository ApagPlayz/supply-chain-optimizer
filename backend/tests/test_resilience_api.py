"""
RED/GREEN tests for Phase 6 Scenario API endpoints.

Tasks 1-5: Distributor failure, geopolitical risk, delivery-target scenarios.
Follows TDD RED → GREEN → REFACTOR cycle.
"""
import pytest
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.scenario import ScenarioCache
from app.models.distributor import Distributor
from app.models.component import Component, DistributorOffer
from app.main import app
from app.core.database import get_db


# ────────────────────────────────────────────────────────────────────────────
# TASK 1: RED tests for ScenarioCache ORM and Alembic migration
# ────────────────────────────────────────────────────────────────────────────

def test_scenario_cache_import():
    """Test that ScenarioCache can be imported from app.models.scenario."""
    from app.models.scenario import ScenarioCache
    assert ScenarioCache is not None
    assert hasattr(ScenarioCache, '__tablename__')
    assert ScenarioCache.__tablename__ == 'scenario_cache'


def test_scenario_cache_columns():
    """Test that ScenarioCache has all required columns."""
    from app.models.scenario import ScenarioCache
    required_cols = ['id', 'scenario_type', 'cache_key', 'result_json',
                     'created_at', 'expires_at', 'accessed_at']
    for col in required_cols:
        assert hasattr(ScenarioCache, col), f"Missing column: {col}"


def test_scenario_cache_in_metadata():
    """Test that 'scenario_cache' table is registered in Base.metadata."""
    from app.core.database import Base
    assert 'scenario_cache' in Base.metadata.tables


def test_alembic_migration_0003():
    """Test that Alembic migration file 0003 exists and has correct structure."""
    import importlib.util
    from pathlib import Path
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "versions" / "0003_scenario_cache.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0003",
        str(migration_path),
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == '0003'
    assert migration.down_revision == '0002'
    assert hasattr(migration, 'upgrade')
    assert hasattr(migration, 'downgrade')


def test_models_init_exports_scenario_cache():
    """Test that ScenarioCache is exported from app.models.__init__."""
    from app.models import ScenarioCache
    assert ScenarioCache is not None


# ────────────────────────────────────────────────────────────────────────────
# TASK 2: RED tests for POST /resilience/distributor-failure endpoint
# ────────────────────────────────────────────────────────────────────────────

def test_distributor_failure_accepts_request(db_session):
    """Test POST /api/v1/resilience/distributor-failure accepts valid request."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_distributor_failure_response_structure(db_session):
    """Test that distributor-failure response has all required fields."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        required_fields = [
            'baseline_cost_usd', 'scenario_cost_usd', 'cost_delta_pct',
            'baseline_eta_days', 'scenario_eta_days', 'eta_delta_days',
            'baseline_risk_score', 'scenario_risk_score', 'risk_delta',
            'baseline_fulfillment_p10', 'baseline_fulfillment_p50', 'baseline_fulfillment_p90',
            'scenario_fulfillment_p10', 'scenario_fulfillment_p50', 'scenario_fulfillment_p90',
            'affected_bom_ids', 'affected_suppliers',
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
    finally:
        app.dependency_overrides.clear()


def test_distributor_failure_simulation_accuracy(db_session):
    """Test that distributor-failure simulation produces realistic deltas."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        assert data['baseline_fulfillment_p10'] <= data['baseline_fulfillment_p50']
        assert data['baseline_fulfillment_p50'] <= data['baseline_fulfillment_p90']
        assert data['scenario_fulfillment_p10'] <= data['scenario_fulfillment_p50']
        assert data['scenario_fulfillment_p50'] <= data['scenario_fulfillment_p90']
    finally:
        app.dependency_overrides.clear()


def test_distributor_failure_caching(db_session):
    """Test that repeated calls to distributor-failure return cached result."""
    import time
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response1 = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        assert response1.status_code == 200
        data1 = response1.json()

        time.sleep(0.05)

        start = time.time()
        response2 = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        elapsed = (time.time() - start) * 1000
        assert response2.status_code == 200
        data2 = response2.json()

        assert data1 == data2
        assert elapsed < 10
    finally:
        app.dependency_overrides.clear()


def test_distributor_failure_cache_expired(db_session):
    """Test that expired cache entries are recomputed."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response1 = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        assert response1.status_code == 200
        data1 = response1.json()

        cache_entries = db_session.query(ScenarioCache).all()
        if cache_entries:
            for entry in cache_entries:
                entry.expires_at = datetime.utcnow() - timedelta(hours=1)
            db_session.commit()

        response2 = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": [1]},
        )
        assert response2.status_code == 200
        data2 = response2.json()

        assert data1 == data2
    finally:
        app.dependency_overrides.clear()


# ────────────────────────────────────────────────────────────────────────────
# TASK 3: RED tests for POST /resilience/geopolitical-risk endpoint
# ────────────────────────────────────────────────────────────────────────────

def test_geopolitical_risk_accepts_request(db_session):
    """Test POST /api/v1/resilience/geopolitical-risk accepts valid request."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"risk_multiplier": 2.0, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_geopolitical_risk_response_structure(db_session):
    """Test that geopolitical-risk response has all required fields."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"risk_multiplier": 2.0, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        required_fields = [
            'baseline_cost_usd', 'scenario_cost_usd', 'cost_delta_pct',
            'baseline_eta_days', 'scenario_eta_days', 'eta_delta_days',
            'baseline_risk_score', 'scenario_risk_score', 'risk_delta',
            'baseline_fulfillment_p10', 'baseline_fulfillment_p50', 'baseline_fulfillment_p90',
            'scenario_fulfillment_p10', 'scenario_fulfillment_p50', 'scenario_fulfillment_p90',
            'affected_bom_ids',
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
    finally:
        app.dependency_overrides.clear()


def test_geopolitical_risk_feed_override(db_session):
    """Test that risk_multiplier properly overrides live feeds."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"risk_multiplier": 2.0, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        assert data['risk_delta'] >= 0
    finally:
        app.dependency_overrides.clear()


def test_geopolitical_risk_tier_migration(db_session):
    """Test that risk_multiplier can cause component tier migrations."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"risk_multiplier": 2.0, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data['affected_bom_ids'], list)
    finally:
        app.dependency_overrides.clear()


def test_geopolitical_risk_caching(db_session):
    """Test that repeated geopolitical-risk calls return cached result."""
    import time
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response1 = client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"risk_multiplier": 2.0, "bom_component_ids": [1]},
        )
        assert response1.status_code == 200
        data1 = response1.json()

        time.sleep(0.05)

        start = time.time()
        response2 = client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"risk_multiplier": 2.0, "bom_component_ids": [1]},
        )
        elapsed = (time.time() - start) * 1000
        assert response2.status_code == 200
        data2 = response2.json()

        assert data1 == data2
        assert elapsed < 10
    finally:
        app.dependency_overrides.clear()


# ────────────────────────────────────────────────────────────────────────────
# TASK 4: RED tests for POST /resilience/delivery-target endpoint
# ────────────────────────────────────────────────────────────────────────────

def test_delivery_target_accepts_request(db_session):
    """Test POST /api/v1/resilience/delivery-target accepts valid request."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 14, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_response_structure(db_session):
    """Test that delivery-target response has all required fields."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 14, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        required_fields = [
            'baseline_cost_usd', 'scenario_cost_usd', 'cost_delta_pct',
            'baseline_eta_days', 'scenario_eta_days', 'eta_delta_days',
            'baseline_risk_score', 'scenario_risk_score', 'risk_delta',
            'baseline_fulfillment_p10', 'baseline_fulfillment_p50', 'baseline_fulfillment_p90',
            'scenario_fulfillment_p10', 'scenario_fulfillment_p50', 'scenario_fulfillment_p90',
            'suppliers_capable', 'suppliers_cannot_meet',
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_tight_constraint(db_session):
    """Test that tight delivery target increases cost."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 14, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        assert data['scenario_cost_usd'] >= data['baseline_cost_usd']
        assert isinstance(data['suppliers_capable'], list)
        assert isinstance(data['suppliers_cannot_meet'], list)
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_impossible(db_session):
    """Test that impossible delivery target is handled gracefully."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 1, "bom_component_ids": [1]},
        )
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, dict)
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_caching(db_session):
    """Test that repeated delivery-target calls return cached result."""
    import time
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    comp = Component(id=1, mpn="TEST-001", manufacturer="TestMfg", category="Test", risk_score=0.3)
    db_session.add(comp)
    db_session.commit()

    offer = DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1)
    db_session.add(offer)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response1 = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 14, "bom_component_ids": [1]},
        )
        assert response1.status_code == 200
        data1 = response1.json()

        time.sleep(0.05)

        start = time.time()
        response2 = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 14, "bom_component_ids": [1]},
        )
        elapsed = (time.time() - start) * 1000
        assert response2.status_code == 200
        data2 = response2.json()

        assert data1 == data2
        assert elapsed < 10
    finally:
        app.dependency_overrides.clear()


# ────────────────────────────────────────────────────────────────────────────
# TASK 5: Integration test for resilience router registration
# ────────────────────────────────────────────────────────────────────────────

def test_resilience_endpoints_registered(db_session):
    """Test that all resilience endpoints are registered in FastAPI app."""
    dist = Distributor(id=1, name="TestDist", latitude=0, longitude=0,
                      city="Test", state="TS", country="USA", is_domestic=True)
    db_session.add(dist)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        endpoints = [
            ("/api/v1/resilience/distributor-failure", {"distributor_id": 1, "bom_component_ids": [1]}),
            ("/api/v1/resilience/geopolitical-risk", {"risk_multiplier": 2.0, "bom_component_ids": [1]}),
            ("/api/v1/resilience/delivery-target", {"target_delivery_days": 14, "bom_component_ids": [1]}),
        ]
        for endpoint, body in endpoints:
            response = client.post(endpoint, json=body)
            assert response.status_code != 404, f"Endpoint {endpoint} not registered"
    finally:
        app.dependency_overrides.clear()


# ────────────────────────────────────────────────────────────────────────────
# P0 regression: scenario outputs must be DATA-DERIVED (real Monte Carlo +
# real distributor geography), never the old hardcoded constants.
# ────────────────────────────────────────────────────────────────────────────

def _override(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    return override_get_db


def test_distributor_failure_is_real_monte_carlo(db_session):
    """Fulfillment percentiles must come from the real Monte Carlo cascade, not the
    old hardcoded baseline (0.7/0.85/0.95) and scenario (0.6/0.75/0.90) placeholders.
    Failing a distributor must be weakly worse than baseline."""
    dists = [
        Distributor(id=i, name=f"D{i}", latitude=35.1 + i, longitude=-90.0 - i,
                    city="C", state="TN", country="USA", is_domestic=True)
        for i in (1, 2, 3)
    ]
    db_session.add_all(dists)
    db_session.commit()
    for cid in range(1, 7):
        db_session.add(Component(id=cid, mpn=f"C{cid}", manufacturer="M", category="Test", risk_score=0.3))
    db_session.commit()
    # d1 is sole/major supplier of several lines so its failure clearly bites.
    pairs = [(1, 1), (2, 1), (3, 1), (3, 2), (4, 2), (4, 3), (5, 2), (6, 3)]
    for oid, (cid, did) in enumerate(pairs, start=1):
        db_session.add(DistributorOffer(id=oid, component_id=cid, distributor_id=did, price=10.0, stock=100, moq=1))
    db_session.commit()

    bom = [1, 2, 3, 4, 5, 6]
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        data = client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1, "bom_component_ids": bom},
        ).json()
        base = (data["baseline_fulfillment_p10"], data["baseline_fulfillment_p50"], data["baseline_fulfillment_p90"])
        scen = (data["scenario_fulfillment_p10"], data["scenario_fulfillment_p50"], data["scenario_fulfillment_p90"])
        # Real, non-degenerate baseline distribution.
        assert data["baseline_fulfillment_p50"] > 0.0
        assert base[0] <= base[1] <= base[2] and scen[0] <= scen[1] <= scen[2]
        # The old hardcoded placeholder vectors must be gone.
        assert base != (0.7, 0.85, 0.95)
        assert scen != (0.6, 0.75, 0.90)
        # Failing a real supplier is weakly worse than baseline.
        assert data["scenario_fulfillment_p50"] <= data["baseline_fulfillment_p50"]
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_capability_is_geography_derived(db_session):
    """A far international supplier must fail a tight delivery window while a
    hub-local domestic supplier meets it — proving lead times come from real
    haversine geography, not the old hardcoded 10/21 days."""
    near = Distributor(id=1, name="NearHub", latitude=35.15, longitude=-90.05,
                       city="Memphis", state="TN", country="USA", is_domestic=True)
    far = Distributor(id=2, name="FarIntl", latitude=51.5, longitude=0.0,
                      city="London", state="", country="UK", is_domestic=False)
    db_session.add_all([near, far])
    db_session.commit()
    comp = Component(id=1, mpn="CMP-001", manufacturer="Mfg", category="Test", risk_score=0.2)
    db_session.add(comp)
    db_session.commit()
    db_session.add_all([
        DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1),
        DistributorOffer(id=2, component_id=1, distributor_id=2, price=9.0, stock=100, moq=1),
    ])
    db_session.commit()

    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        data = client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_delivery_days": 3, "bom_component_ids": [1]},
        ).json()
        capable = {s["name"] for s in data["suppliers_capable"]}
        cannot = {s["name"] for s in data["suppliers_cannot_meet"]}
        assert "NearHub" in capable          # ~2 days, meets 3-day window
        assert "FarIntl" in cannot           # transatlantic + customs, cannot
        # Lead times are real fractional/geography values, not the old 10/21 constants.
        near_lead = next(s["lead_time_days"] for s in data["suppliers_capable"] if s["name"] == "NearHub")
        assert near_lead != 10
    finally:
        app.dependency_overrides.clear()


def test_geopolitical_higher_stress_is_monotonically_worse(db_session):
    """A larger risk multiplier must not improve fulfillment — the elevated-stress
    Monte Carlo should be weakly worse, proving fulfillment responds to the input."""
    # Two distributors both supplying one component so betweenness is non-trivial.
    d1 = Distributor(id=1, name="D1", latitude=35.1, longitude=-90.0, city="A", state="TN", country="USA", is_domestic=True)
    d2 = Distributor(id=2, name="D2", latitude=40.0, longitude=-75.0, city="B", state="PA", country="USA", is_domestic=True)
    db_session.add_all([d1, d2])
    db_session.commit()
    for cid in (1, 2, 3):
        db_session.add(Component(id=cid, mpn=f"C{cid}", manufacturer="M", category="Test", risk_score=0.5))
    db_session.commit()
    oid = 1
    for cid in (1, 2, 3):
        for did in (1, 2):
            db_session.add(DistributorOffer(id=oid, component_id=cid, distributor_id=did, price=5.0, stock=50, moq=1))
            oid += 1
    db_session.commit()

    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        low = client.post("/api/v1/resilience/geopolitical-risk",
                          json={"risk_multiplier": 1.0, "bom_component_ids": [1, 2, 3]}).json()
        high = client.post("/api/v1/resilience/geopolitical-risk",
                           json={"risk_multiplier": 5.0, "bom_component_ids": [1, 2, 3]}).json()
        # Higher geopolitical stress is weakly worse for fulfillment.
        assert high["scenario_fulfillment_p50"] <= low["scenario_fulfillment_p50"]
        # And cost is weakly higher under more stress.
        assert high["scenario_cost_usd"] >= low["scenario_cost_usd"]
    finally:
        app.dependency_overrides.clear()
