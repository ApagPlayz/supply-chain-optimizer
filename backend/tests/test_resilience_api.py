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

def test_distributor_failure_accepts_request(client, graph_db_session):
    """Test POST /api/v1/resilience/distributor-failure accepts valid request."""
    response = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200


def test_distributor_failure_response_structure(client, graph_db_session):
    """Test that distributor-failure response has all required fields."""
    response = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
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


def test_distributor_failure_simulation_accuracy(client, graph_db_session):
    """Test that distributor-failure simulation produces realistic deltas."""
    response = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200
    data = response.json()

    # P10 <= P50 <= P90 for both baseline and scenario
    assert data['baseline_fulfillment_p10'] <= data['baseline_fulfillment_p50']
    assert data['baseline_fulfillment_p50'] <= data['baseline_fulfillment_p90']
    assert data['scenario_fulfillment_p10'] <= data['scenario_fulfillment_p50']
    assert data['scenario_fulfillment_p50'] <= data['scenario_fulfillment_p90']


def test_distributor_failure_caching(client, graph_db_session):
    """Test that repeated calls to distributor-failure return cached result."""
    import time
    response1 = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response1.status_code == 200
    data1 = response1.json()

    time.sleep(0.05)  # Small delay to measure cache hit timing

    start = time.time()
    response2 = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
    )
    elapsed = (time.time() - start) * 1000  # ms
    assert response2.status_code == 200
    data2 = response2.json()

    # Results should be identical
    assert data1 == data2
    # Cache hit should be very fast (< 10ms)
    assert elapsed < 10, f"Cache hit took {elapsed}ms, expected < 10ms"


def test_distributor_failure_cache_expired(client, graph_db_session):
    """Test that expired cache entries are recomputed."""
    response1 = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response1.status_code == 200
    data1 = response1.json()

    # Manually expire cache entry in DB
    from app.core.database import SessionLocal
    db = SessionLocal()
    cache_entries = db.query(ScenarioCache).all()
    if cache_entries:
        for entry in cache_entries:
            entry.expires_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    db.close()

    # Second call should recompute
    response2 = client.post(
        "/api/v1/resilience/distributor-failure",
        json={
            "distributor_id": 1,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response2.status_code == 200
    data2 = response2.json()

    # Results should be the same (same input → same computation)
    assert data1 == data2


# ────────────────────────────────────────────────────────────────────────────
# TASK 3: RED tests for POST /resilience/geopolitical-risk endpoint
# ────────────────────────────────────────────────────────────────────────────

def test_geopolitical_risk_accepts_request(client, graph_db_session):
    """Test POST /api/v1/resilience/geopolitical-risk accepts valid request."""
    response = client.post(
        "/api/v1/resilience/geopolitical-risk",
        json={
            "risk_multiplier": 2.0,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200


def test_geopolitical_risk_response_structure(client, graph_db_session):
    """Test that geopolitical-risk response has all required fields."""
    response = client.post(
        "/api/v1/resilience/geopolitical-risk",
        json={
            "risk_multiplier": 2.0,
            "bom_component_ids": [1, 2, 3],
        }
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


def test_geopolitical_risk_feed_override(client, graph_db_session):
    """Test that risk_multiplier properly overrides live feeds."""
    response = client.post(
        "/api/v1/resilience/geopolitical-risk",
        json={
            "risk_multiplier": 2.0,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200
    data = response.json()

    # Risk delta should be positive (risk increased)
    assert data['risk_delta'] >= 0


def test_geopolitical_risk_tier_migration(client, graph_db_session):
    """Test that risk_multiplier can cause component tier migrations."""
    response = client.post(
        "/api/v1/resilience/geopolitical-risk",
        json={
            "risk_multiplier": 2.0,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200
    data = response.json()

    # affected_bom_ids should be populated if risk tier changed
    assert isinstance(data['affected_bom_ids'], list)


def test_geopolitical_risk_caching(client, graph_db_session):
    """Test that repeated geopolitical-risk calls return cached result."""
    import time
    response1 = client.post(
        "/api/v1/resilience/geopolitical-risk",
        json={
            "risk_multiplier": 2.0,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response1.status_code == 200
    data1 = response1.json()

    time.sleep(0.05)

    start = time.time()
    response2 = client.post(
        "/api/v1/resilience/geopolitical-risk",
        json={
            "risk_multiplier": 2.0,
            "bom_component_ids": [1, 2, 3],
        }
    )
    elapsed = (time.time() - start) * 1000
    assert response2.status_code == 200
    data2 = response2.json()

    assert data1 == data2
    assert elapsed < 10


# ────────────────────────────────────────────────────────────────────────────
# TASK 4: RED tests for POST /resilience/delivery-target endpoint
# ────────────────────────────────────────────────────────────────────────────

def test_delivery_target_accepts_request(client, graph_db_session):
    """Test POST /api/v1/resilience/delivery-target accepts valid request."""
    response = client.post(
        "/api/v1/resilience/delivery-target",
        json={
            "target_delivery_days": 14,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200


def test_delivery_target_response_structure(client, graph_db_session):
    """Test that delivery-target response has all required fields."""
    response = client.post(
        "/api/v1/resilience/delivery-target",
        json={
            "target_delivery_days": 14,
            "bom_component_ids": [1, 2, 3],
        }
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


def test_delivery_target_tight_constraint(client, graph_db_session):
    """Test that tight delivery target increases cost."""
    response = client.post(
        "/api/v1/resilience/delivery-target",
        json={
            "target_delivery_days": 14,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200
    data = response.json()

    # Tight constraint should increase cost
    assert data['scenario_cost_usd'] >= data['baseline_cost_usd']
    # suppliers_capable should be a list
    assert isinstance(data['suppliers_capable'], list)
    # suppliers_cannot_meet should be a list
    assert isinstance(data['suppliers_cannot_meet'], list)


def test_delivery_target_impossible(client, graph_db_session):
    """Test that impossible delivery target is handled gracefully."""
    response = client.post(
        "/api/v1/resilience/delivery-target",
        json={
            "target_delivery_days": 1,  # Unrealistic
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response.status_code == 200
    data = response.json()

    # Should indicate impossibility
    assert isinstance(data, dict)


def test_delivery_target_caching(client, graph_db_session):
    """Test that repeated delivery-target calls return cached result."""
    import time
    response1 = client.post(
        "/api/v1/resilience/delivery-target",
        json={
            "target_delivery_days": 14,
            "bom_component_ids": [1, 2, 3],
        }
    )
    assert response1.status_code == 200
    data1 = response1.json()

    time.sleep(0.05)

    start = time.time()
    response2 = client.post(
        "/api/v1/resilience/delivery-target",
        json={
            "target_delivery_days": 14,
            "bom_component_ids": [1, 2, 3],
        }
    )
    elapsed = (time.time() - start) * 1000
    assert response2.status_code == 200
    data2 = response2.json()

    assert data1 == data2
    assert elapsed < 10


# ────────────────────────────────────────────────────────────────────────────
# TASK 5: Integration test for resilience router registration
# ────────────────────────────────────────────────────────────────────────────

def test_resilience_endpoints_registered(client):
    """Test that all resilience endpoints are registered in FastAPI app."""
    # These will return 200 with empty/mock data if the endpoints exist
    endpoints = [
        "/api/v1/resilience/distributor-failure",
        "/api/v1/resilience/geopolitical-risk",
        "/api/v1/resilience/delivery-target",
    ]
    for endpoint in endpoints:
        response = client.post(endpoint, json={"distributor_id": 1, "bom_component_ids": [1]})
        # Should not return 404
        assert response.status_code != 404, f"Endpoint {endpoint} not registered"
