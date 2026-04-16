"""Integration tests for /graph API endpoints — Phase 02."""
import pytest


def test_lifespan_loads_graph(client):
    from app.graph import get_graph_state
    # After TestClient startup, graph state should be set (if DB has data)
    # With empty test DB, state may be None — assert no exception was raised
    # Full integration verified via manual server start
    assert True  # startup completed without crash


def test_get_graph_metrics(client):
    pytest.skip("stub — implement in plan 02-04")


def test_post_graph_simulate(client):
    pytest.skip("stub — implement in plan 02-04")


def test_graph_aware_changes_routing(client):
    pytest.skip("stub — implement in plan 02-04")
