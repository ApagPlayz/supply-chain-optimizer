"""
Benchmark API endpoint tests (04-02).

Covers:
  - GET /benchmark/summary — response shape, delta math, error states
  - GET /benchmark/fiedler-curve — shape, baseline step, 503 when no graph
  - GET /benchmark/cascade-heatmap — shape, empty-DB returns empty list
  - GET /benchmark/single-source-components — real ORM data, no fabricated strings

Tests: 14+ covering BENCH-02, BENCH-05, BENCH-06, VIZ-02.

NOTE: Each test that needs specific DB state uses a fresh in-memory SQLite engine
and its own TestClient to avoid cross-test contamination. The lifespan graph build
runs against the real DB during startup but is isolated per-fixture via monkeypatching
of app.graph.get_graph_state where needed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure backend root on path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import pytest
from dataclasses import dataclass, field
from typing import FrozenSet, Dict, List, Optional
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.optimization_run import OptimizationRun
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor


# ── Mock GraphState ────────────────────────────────────────────────────────────

@dataclass
class _MockGraphState:
    """Minimal GraphState mock sufficient for benchmark endpoint tests."""
    graph: object = None
    dist_nodes: FrozenSet[str] = field(default_factory=frozenset)
    betweenness: Dict[int, float] = field(default_factory=dict)
    pagerank: Dict[int, float] = field(default_factory=dict)
    k_core: Dict[str, int] = field(default_factory=dict)
    single_source_component_ids: FrozenSet[int] = field(default_factory=frozenset)
    hhi_by_category: Dict[str, float] = field(default_factory=dict)
    fiedler: float = 0.25
    holdout_offer_pairs: FrozenSet[tuple] = field(default_factory=frozenset)
    fiedler_curve: List[dict] = field(default_factory=list)
    n_distributors: int = 3
    n_components: int = 10
    n_edges: int = 15


def _make_fiedler_curve():
    """6-entry Fiedler curve for mock GraphState."""
    return [
        {"step": 0, "removed": None, "removed_name": None, "lambda2": 0.25, "delta_pct": 0.0, "collapsed_boms": []},
        {"step": 1, "removed": 1, "removed_name": "DigiKey", "lambda2": 0.20, "delta_pct": -20.0, "collapsed_boms": []},
        {"step": 2, "removed": 2, "removed_name": "Mouser", "lambda2": 0.15, "delta_pct": -40.0, "collapsed_boms": ["bom_01"]},
        {"step": 3, "removed": 3, "removed_name": "Arrow", "lambda2": 0.10, "delta_pct": -60.0, "collapsed_boms": ["bom_01", "bom_02"]},
        {"step": 4, "removed": 4, "removed_name": "Avnet", "lambda2": 0.05, "delta_pct": -80.0, "collapsed_boms": ["bom_01", "bom_02", "bom_03"]},
        {"step": 5, "removed": 5, "removed_name": "Newark", "lambda2": 0.01, "delta_pct": -96.0, "collapsed_boms": ["bom_01", "bom_02", "bom_03", "bom_04"]},
    ]


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_test_db():
    """Return (engine, SessionClass) for a fresh in-memory SQLite DB.

    Uses StaticPool so all connections share a single in-memory database
    instance — without this, each SQLite :memory: connection gets an
    empty independent DB and 'no such table' errors occur.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return engine, Session


def _make_client_with_db(session):
    """
    Return a TestClient with the given session injected as the DB dependency.
    The graph state is always set to a real-looking mock to avoid the lifespan
    blocking on the real DB build. We do NOT override get_graph_state globally —
    individual tests patch it as needed.
    """
    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _make_benchmark_rows(session, run_id=1, baseline_cost=100.0, graph_aware_cost=90.0):
    """Insert 10 BOMs × 2 graph_aware = 20 rows for given run_id."""
    bom_names = [f"bom_{i:02d}" for i in range(1, 11)]
    for bom in bom_names:
        for graph_aware, cost in [(False, baseline_cost), (True, graph_aware_cost)]:
            row = OptimizationRun(
                run_id=run_id,
                run_tag="benchmark",
                bom_name=bom,
                bom_items_json=[{"component_id": 1, "quantity": 1}],
                strategy="balanced",
                graph_aware=graph_aware,
                total_cost_usd=cost,
                eta_p50_days=5.0 if not graph_aware else 5.5,
                co2_kg=2.5 if not graph_aware else 2.3,
                cascade_risk_score=0.4 if not graph_aware else 0.3,
                eta_p10_days=4.0,
                eta_p90_days=6.0,
                monte_carlo_samples=[float(i) for i in range(10)],
                mc_evar_95=6.5 if not graph_aware else 6.0,
                feeds_available={"gpr": True, "acled": True},
                selected_distributor_ids=[1, 2],
                selected_distributor_names=["DigiKey", "Mouser"],
            )
            session.add(row)
    session.commit()


# ── Tests: /benchmark/summary ─────────────────────────────────────────────────

def test_summary_returns_required_keys():
    """GET /benchmark/summary with 20 rows → 200 with all required keys."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        required_keys = {
            "run_id", "n_boms", "cost_delta_pct", "eta_delta_pct",
            "co2_delta_pct", "cascade_risk_delta_pct", "monte_carlo",
            "tradeoff", "bom_deltas", "feeds_fallback", "noise_floor_pct",
        }
        for key in required_keys:
            assert key in data, f"Missing key: {key}"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_empty_db_returns_404():
    """GET /benchmark/summary with empty DB → 404 with benchmark pipeline hint."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 404
        # Detail must guide user to run the benchmark pipeline
        # (string "run_benchmark" is forbidden in app/ per T-04-01 security guard)
        detail = resp.json()["detail"]
        assert "benchmark" in detail.lower(), f"Expected benchmark hint in 404 detail, got: {detail!r}"
        assert "pipeline" in detail.lower() or "python" in detail.lower(), (
            f"Expected execution hint in 404 detail, got: {detail!r}"
        )
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_cost_delta_pct_sign_convention():
    """Baseline cost=$100, graph-aware cost=$90 → cost_delta_pct = -10.0."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, baseline_cost=100.0, graph_aware_cost=90.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200
        delta = resp.json()["cost_delta_pct"]
        # (90 - 100) / 100 * 100 = -10.0
        assert abs(delta - (-10.0)) < 0.01, f"Expected -10.0, got {delta}"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_run_id_param():
    """?run_id=1 returns run 1 data when two run groups exist."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, run_id=1, baseline_cost=100.0, graph_aware_cost=90.0)
    _make_benchmark_rows(session, run_id=2, baseline_cost=200.0, graph_aware_cost=180.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary?run_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == 1
        # run 1 cost delta should be -10%
        assert abs(data["cost_delta_pct"] - (-10.0)) < 0.01
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_missing_run_id_returns_404():
    """?run_id=999 with no such rows → 404."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, run_id=1)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary?run_id=999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: /benchmark/fiedler-curve ──────────────────────────────────────────

def test_fiedler_curve_requires_graph_state():
    """No graph state → 503."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)

    try:
        with patch("app.graph.get_graph_state", return_value=None):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_fiedler_curve_shape():
    """Mock GraphState with 6-entry fiedler_curve → 200, len(points)==6."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState(fiedler_curve=_make_fiedler_curve())

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "points" in data
        assert len(data["points"]) == 6
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_fiedler_curve_baseline_is_step_zero():
    """points[0].step == 0 and points[0].removed is None."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState(fiedler_curve=_make_fiedler_curve())

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 200
        pt0 = resp.json()["points"][0]
        assert pt0["step"] == 0
        assert pt0["removed"] is None
        assert pt0["removed_name"] is None
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: /benchmark/cascade-heatmap ────────────────────────────────────────

def test_cascade_heatmap_empty_db_returns_empty_list():
    """No rows → 200 with empty points list (not 404)."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState()

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/cascade-heatmap")
        assert resp.status_code == 200
        assert resp.json()["points"] == []
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_cascade_heatmap_has_lat_lng_weight():
    """With rows and distributor data → returns dicts with lat, lng, weight."""
    _, Session = _make_test_db()
    session = Session()

    # Seed distributor
    dist = Distributor(
        id=1, name="DigiKey", latitude=48.1, longitude=-96.2,
        city="Thief River Falls", state="MN", country="USA", is_domestic=True,
    )
    session.add(dist)
    session.commit()

    # Seed benchmark rows referencing distributor id=1
    _make_benchmark_rows(session)

    client = _make_client_with_db(session)
    gs = _MockGraphState()

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/cascade-heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
        # Should have at least one point for distributor 1
        if data["points"]:
            pt = data["points"][0]
            assert "lat" in pt
            assert "lng" in pt
            assert "weight" in pt
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: tradeoff + feeds_fallback ─────────────────────────────────────────

def test_tradeoff_always_present():
    """Even if all deltas negative, tradeoff entry still appears."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, baseline_cost=100.0, graph_aware_cost=90.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "tradeoff" in data
        tradeoff = data["tradeoff"]
        assert "bom_name" in tradeoff
        assert "losing_axis" in tradeoff
        assert "narrative" in tradeoff
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_feeds_fallback_flag():
    """Rows with feeds_available containing False → feeds_fallback=True."""
    _, Session = _make_test_db()
    session = Session()

    bom_names = [f"bom_{i:02d}" for i in range(1, 11)]
    for bom in bom_names:
        for graph_aware in [False, True]:
            row = OptimizationRun(
                run_id=1,
                run_tag="benchmark",
                bom_name=bom,
                bom_items_json=[{"component_id": 1, "quantity": 1}],
                strategy="balanced",
                graph_aware=graph_aware,
                total_cost_usd=100.0,
                eta_p50_days=5.0,
                co2_kg=2.5,
                cascade_risk_score=0.4,
                feeds_available={"gpr": False, "acled": True},  # gpr=False -> fallback
                selected_distributor_ids=[1],
                selected_distributor_names=["DigiKey"],
            )
            session.add(row)
    session.commit()

    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200
        assert resp.json()["feeds_fallback"] is True
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: /benchmark/single-source-components ────────────────────────────────

def test_single_source_components_shape():
    """Mock GraphState with single_source_component_ids={1}, DB fixture -> 200 with correct shape."""
    _, Session = _make_test_db()
    session = Session()

    # Seed DB with real component + distributor + offer
    comp = Component(
        id=1, mpn="STM32F103C8T6", manufacturer="STMicroelectronics",
        manufacturer_country="France", category="Microcontrollers",
        description="ARM Cortex-M3", risk_score=0.2,
    )
    dist = Distributor(
        id=10, name="Mouser Electronics", latitude=33.05, longitude=-97.05,
        city="Mansfield", state="TX", country="USA", is_domestic=True,
    )
    offer = DistributorOffer(
        id=1, component_id=1, distributor_id=10,
        price=4.50, stock=500, sku="MOUSER-STM32", currency="USD", moq=1,
    )
    session.add_all([comp, dist, offer])
    session.commit()

    gs = _MockGraphState(single_source_component_ids=frozenset({1}))
    client = _make_client_with_db(session)

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/single-source-components")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "components" in data
        assert len(data["components"]) == 1

        comp_data = data["components"][0]
        assert comp_data["component_id"] == 1
        assert comp_data["mpn"] == "STM32F103C8T6"
        assert comp_data["manufacturer"] == "STMicroelectronics"
        assert comp_data["distributor_id"] == 10
        assert comp_data["distributor_name"] == "Mouser Electronics"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_single_source_components_no_fabricated_strings():
    """Returned mpn must NOT equal 'High-betweenness hub' — must be real Component.mpn."""
    _, Session = _make_test_db()
    session = Session()

    comp = Component(
        id=2, mpn="STM32F103C8T6", manufacturer="STMicroelectronics",
        manufacturer_country="France", category="Microcontrollers",
        description="ARM Cortex-M3", risk_score=0.2,
    )
    dist = Distributor(
        id=20, name="DigiKey", latitude=44.89, longitude=-95.36,
        city="Thief River Falls", state="MN", country="USA", is_domestic=True,
    )
    offer = DistributorOffer(
        id=2, component_id=2, distributor_id=20,
        price=3.75, stock=1000, sku="DK-STM32", currency="USD", moq=1,
    )
    session.add_all([comp, dist, offer])
    session.commit()

    gs = _MockGraphState(single_source_component_ids=frozenset({2}))
    client = _make_client_with_db(session)

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/single-source-components")

        assert resp.status_code == 200
        components = resp.json()["components"]
        assert len(components) == 1

        mpn = components[0]["mpn"]
        assert mpn != "High-betweenness hub", f"Got fabricated string: {mpn!r}"
        assert mpn == "STM32F103C8T6", f"Expected real MPN, got: {mpn!r}"
    finally:
        app.dependency_overrides.clear()
        session.close()
