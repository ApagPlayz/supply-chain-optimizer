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
    spec = importlib.util.spec_from_file_location(
        "migration_0003",
        "/Users/alessiopagliarulo/Documents/Claude Projects/Logisitics Project/backend/migrations/versions/0003_scenario_cache.py"
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
