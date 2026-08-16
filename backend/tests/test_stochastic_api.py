"""
Tests for the cost-vs-CVaR frontier API (app/api/stochastic.py).

The endpoint tests split three ways:

1. **Contract** -- the response carries the frontier, the knee-derived recommendation,
   the solver diagnostics, and the caveats. The caveats are asserted, not decorative:
   they are the disclosure that the disruption probabilities are an assumption, and a
   silent regression that dropped them would be exactly the kind of quiet
   overclaiming this subsystem was built to stop.

2. **Calibration transparency** -- `/stochastic/calibration` must publish the legacy
   simulator's probability next to the calibrated one, and the legacy column must show
   the p = 1.0 saturation while the calibrated column must not.

3. **DoS posture** -- the caller cannot enlarge the compute budget. Draw count and
   lambda grid are server-fixed; BOM size and quantity are capped by the schema.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.graph as graph_state_module
from app.core.database import Base, get_db
from app.main import app
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor

from tests.conftest import TestSession, test_engine

FRONTIER = "/api/v1/stochastic/frontier"
CALIBRATION = "/api/v1/stochastic/calibration"


# 6 distributors x 6 components, deliberately shaped to admit a GRADED cost-vs-risk
# tradeoff rather than a single all-or-nothing switch.
#
# HubCo (id 1) is the cheapest source for every line AND the only distributor touching
# all six components, so the bipartite betweenness projection ranks it top and the
# calibration hands it the highest disruption probability. The rest form a price ladder
# with decreasing centrality. Because each of the six lines can be moved off HubCo
# independently, the (E, CVaR) image has interior points and the lambda sweep produces
# an actual curve -- with only two or three lines it collapses to two vertices and
# there is no knee to find (the convex-hull limitation of a weighted-sum sweep).
_SUPPLIES = {1: [1, 2, 3, 4, 5, 6], 2: [1, 2, 3, 4], 3: [2, 3, 5, 6],
             4: [1, 4, 5, 6], 5: [3, 5], 6: [4, 6]}
_UNIT_BASE = {1: 1.00, 2: 1.20, 3: 1.45, 4: 1.75, 5: 2.10, 6: 2.55}
_STOCK = {1: 6000, 2: 2500, 3: 2000, 4: 2000, 5: 1500, 6: 1500}
_GEO = {
    1: ("HubCo", "Nashville", "TN", 36.16, -86.78),
    2: ("MidCo", "Chicago", "IL", 41.88, -87.63),
    3: ("PlainsCo", "Denver", "CO", 39.74, -104.99),
    4: ("DesertCo", "Phoenix", "AZ", 33.45, -112.07),
    5: ("EdgeCo", "Seattle", "WA", 47.61, -122.33),
    6: ("RimCo", "Portland", "OR", 45.52, -122.68),
}
N_COMPONENTS = 6


@pytest.fixture()
def frontier_db():
    """
    Seed the network above.

    Uses the shared file-backed test engine rather than an in-memory SQLite DB:
    TestClient dispatches requests on a worker thread, and SQLAlchemy's in-memory
    pooling hands a *fresh, empty* database to each new thread, which shows up as
    "no such table: components" from inside the endpoint.
    """
    Base.metadata.create_all(bind=test_engine)
    session = TestSession()

    for did, (name, city, state, lat, lng) in _GEO.items():
        session.add(Distributor(
            id=did, name=name, latitude=lat, longitude=lng, city=city, state=state,
            country="USA", is_domestic=True,
        ))
    for cid in range(1, N_COMPONENTS + 1):
        session.add(Component(
            id=cid, mpn=f"FRONTIER-{cid:03d}", manufacturer="TestCo",
            manufacturer_country="USA", category="Microcontrollers",
            description=f"Frontier test part {cid}", risk_score=0.3,
        ))

    offer_id = 1
    for did, comps in _SUPPLIES.items():
        for cid in comps:
            session.add(DistributorOffer(
                id=offer_id, component_id=cid, distributor_id=did,
                price=round(_UNIT_BASE[did] * (1 + 0.35 * cid), 2),
                stock=_STOCK[did], moq=1, sku=f"SKU-{cid}-{did}", currency="USD",
            ))
            offer_id += 1
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def graph_client(frontier_db):
    """
    TestClient bound to `frontier_db`, with the process-global GraphState cleared so
    the endpoint builds the graph from THIS session. Without that, the app lifespan
    leaves a GraphState built from the real database in place and `_graph()` would
    prefer it -- silently scoring the test's BOM against production betweenness.
    `conftest.restore_process_globals` puts the previous global back afterwards.
    """
    def _override():
        try:
            yield frontier_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        graph_state_module.set_graph_state(None)
        yield client
    app.dependency_overrides.clear()


# ── Contract ─────────────────────────────────────────────────────────────────

def test_frontier_returns_a_swept_frontier(graph_client):
    r = graph_client.post(FRONTIER, json={
        "items": [{"component_id": 1, "quantity": 40},
                  {"component_id": 2, "quantity": 40}],
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert len(body["frontier"]) >= 2
    lambdas = [p["lambda"] for p in body["frontier"]]
    assert lambdas == sorted(lambdas), "frontier must come back in ascending lambda"
    assert lambdas[0] == 0.0 and lambdas[-1] == 1.0

    for point in body["frontier"]:
        assert point["cvar_95_usd"] >= point["expected_cost_usd"] - 1e-6
        assert point["expected_cost_usd"] >= point["first_stage_cost_usd"] - 1e-6
        assert point["n_suppliers"] >= 1
        assert point["solver_status"] in {"OPTIMAL", "FEASIBLE"}


def test_frontier_reports_solver_diagnostics_and_scenario_size(graph_client):
    """Problem size and solve quality are published, not hidden."""
    r = graph_client.post(FRONTIER, json={"items": [{"component_id": 1, "quantity": 50}]})
    assert r.status_code == 200, r.text
    body = r.json()

    solver = body["solver"]
    assert solver["num_search_workers"] == 1
    assert solver["worst_mip_gap_pct"] >= 0.0
    assert isinstance(solver["any_point_hit_time_limit"], bool)

    scen = body["scenarios"]
    assert scen["n_draws"] == 200
    assert 1 <= scen["n_distinct"] <= scen["n_draws"]
    assert 0.0 <= scen["p_no_disruption"] <= 1.0


def test_frontier_always_discloses_that_probabilities_are_assumed(graph_client):
    """
    The caveats are load-bearing. This endpoint's numbers rest on a firm-level base
    rate used per supplier; publishing a CVaR without saying so is the failure mode
    this whole module exists to correct.
    """
    r = graph_client.post(FRONTIER, json={"items": [{"component_id": 1, "quantity": 10}]})
    assert r.status_code == 200, r.text
    caveats = " ".join(r.json()["caveats"]).lower()
    assert "assumption" in caveats
    assert "mckinsey" in caveats
    assert "correlated" in caveats, "independence of failures must be disclosed"
    assert "convex hull" in caveats, "the weighted-sum limitation must be disclosed"


def test_lower_disruption_probability_gives_a_lower_tail(graph_client):
    """The base rate is a real dial, not decoration."""
    def cvar_at(base_prob: float) -> float:
        r = graph_client.post(FRONTIER, json={
            "items": [{"component_id": 1, "quantity": 50}],
            "base_annual_prob": base_prob,
        })
        assert r.status_code == 200, r.text
        return max(p["cvar_95_usd"] for p in r.json()["frontier"])

    assert cvar_at(0.02) <= cvar_at(0.40)


def test_shorter_horizon_gives_a_lower_tail(graph_client):
    """A 7-day exposure window cannot be riskier than a 365-day one."""
    def cvar_at(days: int) -> float:
        r = graph_client.post(FRONTIER, json={
            "items": [{"component_id": 1, "quantity": 50}],
            "horizon_days": days,
        })
        assert r.status_code == 200, r.text
        return max(p["cvar_95_usd"] for p in r.json()["frontier"])

    assert cvar_at(7) <= cvar_at(365)


def test_recommendation_is_expressed_as_a_decision(graph_client):
    """
    The deliverable is not the knee's coordinates, it is the trade the knee implies:
    what a dollar of extra expected cost buys in tail reduction before it, versus
    after. Both ratios must be present and must tell the story in the right direction.
    """
    r = graph_client.post(FRONTIER, json={
        "items": [{"component_id": c, "quantity": 600} for c in range(1, 7)],
    })
    assert r.status_code == 200, r.text
    rec = r.json()["recommendation"]
    assert rec is not None, (
        "this fixture is built to have a graded frontier; a None recommendation means "
        "the sweep collapsed to fewer than three distinct non-dominated points"
    )
    assert 0.0 <= rec["knee_lambda"] <= 1.0
    assert rec["cvar_reduction_usd"] > 0.0, "the knee must actually reduce the tail"
    assert rec["extra_expected_cost_usd"] > 0.0, "and it must cost something"
    assert rec["cvar_removed_per_dollar_spent"] > rec[
        "cvar_removed_per_dollar_spent_beyond_knee"
    ], "resilience must be a worse buy after the knee than before it -- that IS the knee"
    assert rec["statement"]


def test_recommendation_is_none_rather_than_invented_on_a_flat_frontier(graph_client):
    """
    A single-line BOM off one supplier has nothing to trade off. The endpoint must say
    so rather than nominate an arbitrary point as "the recommendation".
    """
    r = graph_client.post(FRONTIER, json={"items": [{"component_id": 5, "quantity": 5}]})
    assert r.status_code == 200, r.text
    assert r.json()["recommendation"] is None


def test_second_identical_request_is_served_from_cache(graph_client):
    payload = {"items": [{"component_id": 1, "quantity": 25}]}
    first = graph_client.post(FRONTIER, json=payload)
    second = graph_client.post(FRONTIER, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["frontier"] == first.json()["frontier"]


def test_unknown_component_is_a_404(graph_client):
    r = graph_client.post(FRONTIER, json={"items": [{"component_id": 999999, "quantity": 1}]})
    assert r.status_code == 404


def test_unknown_strategy_is_a_400(graph_client):
    r = graph_client.post(FRONTIER, json={
        "items": [{"component_id": 1, "quantity": 1}], "strategy": "nonsense",
    })
    assert r.status_code == 400


def test_quantity_beyond_available_stock_is_a_422_not_a_500(graph_client):
    """An infeasible BOM is the caller's problem, and must be reported as one."""
    r = graph_client.post(FRONTIER, json={
        "items": [{"component_id": 1, "quantity": 100000}],
    })
    assert r.status_code == 422


# ── Calibration transparency ─────────────────────────────────────────────────

def test_calibration_publishes_the_legacy_probability_beside_the_calibrated_one(graph_client):
    r = graph_client.get(CALIBRATION)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["distributors"], "expected at least one distributor"
    for row in body["distributors"]:
        assert row["legacy_simulator_p_fail"] == pytest.approx(
            row["betweenness_normalized"]
        ), "the legacy column must be the raw betweenness, verbatim"
        assert row["p_disruption_over_horizon"] < 1.0

    contrast = body["contrast_with_existing_simulator"]
    assert contrast["max_calibrated_p_fail"] < contrast["max_legacy_p_fail"] or \
        contrast["max_legacy_p_fail"] == 0.0
    assert body["base_rate_source"]["citation"].startswith("McKinsey")
    assert "known_weakness" in body["base_rate_source"]


def test_calibration_spread_of_one_flattens_every_probability(graph_client):
    r = graph_client.get(CALIBRATION, params={"centrality_spread": 1.0})
    assert r.status_code == 200, r.text
    probs = {row["p_disruption_over_horizon"] for row in r.json()["distributors"]}
    assert len(probs) == 1, (
        "spread=1.0 is the 'centrality tells us nothing' arm; every supplier must sit "
        "on the flat base rate"
    )


def test_calibration_rejects_out_of_range_parameters(graph_client):
    assert graph_client.get(CALIBRATION, params={"base_annual_prob": 1.5}).status_code == 400
    assert graph_client.get(CALIBRATION, params={"horizon_days": 0}).status_code == 400
    assert graph_client.get(CALIBRATION, params={"centrality_spread": 0.2}).status_code == 400


# ── DoS posture ──────────────────────────────────────────────────────────────

def test_caller_cannot_enlarge_the_compute_budget(graph_client):
    """
    Draw count and lambda grid are server-fixed (the T-02-03 mitigation pattern from
    graph/simulation.py). Supplying them must not change the work done.
    """
    r = graph_client.post(FRONTIER, json={
        "items": [{"component_id": 1, "quantity": 20}],
        "n_draws": 100000,
        "lambda_grid": [0.0, 0.01, 0.02, 0.03],
        "time_limit_s": 600,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenarios"]["n_draws"] == 200
    assert len(body["frontier"]) == 6
    assert body["solver"]["max_time_in_seconds_per_point"] == 5.0


def test_bom_size_and_quantity_are_capped_by_the_schema(graph_client):
    too_many = graph_client.post(FRONTIER, json={
        "items": [{"component_id": 1, "quantity": 1} for _ in range(26)],
    })
    assert too_many.status_code == 422

    too_big = graph_client.post(FRONTIER, json={
        "items": [{"component_id": 1, "quantity": 100001}],
    })
    assert too_big.status_code == 422
