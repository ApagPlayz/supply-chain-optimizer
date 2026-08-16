"""
Regression tests for the 2026-08 functionality audit.

Every bug pinned here is the same failure mode: an endpoint that returns a
CONFIDENT, WELL-FORMED, 200 response which does not depend on its input.

  * `/graph/metrics` published PageRank 0.0 for all 92 distributors — a min-max
    rescale of a constant vector.
  * `/graph/simulate` returned p10 = p50 = p90 = cvar_95 = 1.0 for a 5-part BOM, for
    a 1-part BOM, and for an EMPTY BOM.
  * `/resilience/*` returned zero impact for 91 of 92 distributors, because the most
    central distributor already had a failure probability of exactly 1.0 at baseline,
    so forcing it to fail changed nothing.
  * `/resilience/delivery-target` echoed the requested target back as the achieved ETA.
  * `POST /api/v1/cart` accepted quantity = -5 with 201 Created.

Structural emptiness that looks like success is this project's recurring failure, so
these tests assert on the RELATIONSHIP between input and output, not just on shape.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.models.distributor import Distributor
from app.models.component import Component, DistributorOffer


def _override(session):
    def _dep():
        try:
            yield session
        finally:
            pass
    return _dep


# ════════════════════════════════════════════════════════════════════════════
# Item 3 — centrality metrics must carry information
# ════════════════════════════════════════════════════════════════════════════

def test_pagerank_is_not_identically_zero(graph_db_session):
    """PageRank published 0.0 for every distributor. Two compounding causes:

    it was run on the DiGraph (all edges distributor->component, so every
    distributor had in-degree 0 and received only the uniform teleport share —
    identical values), and that constant vector was then min-max normalized, which
    maps a zero-range vector to all-zeros.
    """
    from app.graph.builder import build_graph_state
    gs = build_graph_state(graph_db_session)

    assert gs.pagerank, "pagerank dict is empty"
    values = list(gs.pagerank.values())
    assert sum(values) > 0.0, f"PageRank sums to {sum(values)} — the audited bug"
    assert max(values) > 0.0, f"PageRank max is {max(values)} — the audited bug"
    assert len(set(round(v, 12) for v in values)) > 1, (
        "PageRank resolved to a single value for every distributor; it is a constant, "
        f"not a metric: {values}"
    )


def test_no_centrality_is_min_max_rescaled(graph_db_session):
    """A min-max rescale is what manufactured both the PageRank zeros and the
    p_fail = 1.0 pathology. Raw scores must not be pinned to the [0, 1] endpoints."""
    from app.graph.builder import build_graph_state
    gs = build_graph_state(graph_db_session)

    # PageRank on a bipartite graph distributes mass over BOTH partitions, so the
    # distributor sub-total is strictly below 1 and no distributor can reach 1.0.
    assert max(gs.pagerank.values()) < 1.0
    assert sum(gs.pagerank.values()) < 1.0

    # Betweenness may legitimately be 0.0 for a peripheral node, but a min-max
    # rescale would force the maximum to EXACTLY 1.0. On this fixture the raw
    # bipartite betweenness of the hub is strictly below its theoretical maximum.
    assert max(gs.betweenness.values()) != 1.0, (
        "max(betweenness) is exactly 1.0 — the min-max rescale is back, and with it "
        "a distributor that fails in 100% of Monte Carlo scenarios"
    )


def test_n_edges_is_the_graph_edge_count_not_the_offer_row_count(graph_db_session):
    """/graph/metrics reported n_edges 8,176 for a graph holding 5,789 edges."""
    from app.graph.builder import build_graph_state
    gs = build_graph_state(graph_db_session)

    assert gs.n_edges == gs.graph.number_of_edges()
    assert gs.n_offer_rows >= gs.n_edges
    # The whole difference must be accounted for, not hand-waved.
    assert gs.n_edges == (
        gs.n_offer_rows - gs.n_holdout_offer_rows - gs.n_duplicate_offer_rows
    )


# ════════════════════════════════════════════════════════════════════════════
# Item 5 — p_fail must be a calibrated probability, not a centrality score
# ════════════════════════════════════════════════════════════════════════════

def test_p_disruption_is_calibrated_not_betweenness(graph_db_session):
    from app.graph.builder import build_graph_state
    gs = build_graph_state(graph_db_session)

    assert gs.p_disruption, "p_disruption was never populated"
    assert set(gs.p_disruption) == set(gs.betweenness)
    # It must not simply BE the betweenness vector.
    assert gs.p_disruption != gs.betweenness

    probs = list(gs.p_disruption.values())
    assert all(0.0 < p < 1.0 for p in probs), probs
    # No supplier may be modelled as certain to fail — that is the exact defect.
    assert max(probs) <= 0.5, max(probs)
    # And none may be modelled as immortal.
    assert min(probs) > 0.0, min(probs)

    cal = gs.p_disruption_calibration
    for key in ("base_annual_prob", "horizon_days", "centrality_spread",
                "base_horizon_prob", "max_failure_prob", "source", "method"):
        assert key in cal, f"calibration provenance missing {key}"


def test_forcing_the_most_central_distributor_is_not_a_no_op(graph_db_session):
    """The audited symptom: 91 of 92 distributors produced literally zero impact,
    because the top-centrality distributor already failed in every baseline
    scenario. Forcing it must now change the simulation on a BOM it can break."""
    from app.graph.builder import build_graph_state
    from app.graph.simulation import run_monte_carlo
    gs = build_graph_state(graph_db_session)

    top = max(gs.betweenness, key=lambda d: gs.betweenness[d])
    assert gs.p_disruption[top] < 1.0, (
        "the most central distributor still has p_fail 1.0 at baseline"
    )

    # Components 6-10 are single-sourced from distributor 1 in the fixture.
    single_sourced = sorted(graph_db_session.query(Component.id).all())
    bom = [cid for (cid,) in single_sourced if cid >= 6]
    baseline = run_monte_carlo(gs, bom)
    forced = run_monte_carlo(gs, bom, forced_failures={1})

    assert forced.p50 < baseline.p50 or forced.mean_cost_inflation > baseline.mean_cost_inflation, (
        f"forcing distributor 1 changed nothing: baseline p50={baseline.p50} "
        f"mean_inf={baseline.mean_cost_inflation}, forced p50={forced.p50} "
        f"mean_inf={forced.mean_cost_inflation}"
    )
    assert forced.n_forced_failures == 1


# ════════════════════════════════════════════════════════════════════════════
# Item 4 — /graph/simulate must depend on its input
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def graph_client(graph_db_session):
    from app.graph import set_graph_state
    from app.graph.builder import build_graph_state
    set_graph_state(build_graph_state(graph_db_session))
    app.dependency_overrides[get_db] = _override(graph_db_session)
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        set_graph_state(None)


def test_simulate_rejects_an_empty_bom(graph_client):
    """`[]` used to return the SAME 1.0/1.0/1.0/1.0 body as a real 5-part BOM,
    which is what proved the endpoint ignored its input."""
    resp = graph_client.post("/api/v1/graph/simulate", json={"bom_component_ids": []})
    assert resp.status_code == 422, resp.text


def test_simulate_404s_on_unknown_component_ids(graph_client):
    """Unknown ids returned 200 while silently counting every missing line as
    unfulfillable, inflating cvar_95 for a BOM the caller never asked about."""
    resp = graph_client.post(
        "/api/v1/graph/simulate", json={"bom_component_ids": [999_999]}
    )
    assert resp.status_code == 404, resp.text
    assert "999999" in resp.text


def test_simulate_output_depends_on_the_bom(graph_client):
    """A diversified BOM and a single-sourced BOM must not produce identical bodies."""
    diversified = graph_client.post(
        "/api/v1/graph/simulate", json={"bom_component_ids": [1, 2, 3, 4, 5]}
    )
    single_sourced = graph_client.post(
        "/api/v1/graph/simulate", json={"bom_component_ids": [6, 7, 8, 9, 10]}
    )
    assert diversified.status_code == 200, diversified.text
    assert single_sourced.status_code == 200, single_sourced.text

    a, b = diversified.json(), single_sourced.json()
    assert a != b, "two structurally different BOMs returned an identical body"

    # The scope block must reflect what was actually asked.
    assert a["scope"]["n_bom_lines"] == 5
    assert b["scope"]["n_bom_lines"] == 5
    # Components 6-10 have exactly one stocked distributor in the fixture.
    assert b["scope"]["n_single_source_lines"] > a["scope"]["n_single_source_lines"]
    # And the single-sourced BOM must actually experience shortfall scenarios.
    assert b["scope"]["n_scenarios_with_shortfall"] > 0
    # The published scope must differ too — it is the evidence that the percentiles
    # describe THIS BOM rather than a constant.
    assert a["scope"] != b["scope"]
    assert a["scope"]["n_suppliers_in_scope"] != b["scope"]["n_suppliers_in_scope"]


def test_simulate_scope_tracks_bom_length(graph_client):
    for bom in ([1], [1, 2], [1, 2, 3, 4, 5]):
        resp = graph_client.post(
            "/api/v1/graph/simulate", json={"bom_component_ids": bom}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["scope"]["n_bom_lines"] == len(bom)


def test_graph_metrics_publishes_the_probability_model(graph_client):
    resp = graph_client.get("/api/v1/graph/metrics")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["n_edges"] != data["n_offer_rows"] or data["n_holdout_offer_rows"] == 0
    assert sum(data["pagerank"].values()) > 0.0
    assert data["p_disruption"], "p_disruption not published"
    assert data["p_disruption_calibration"]["max_failure_prob"] <= 0.5


# ════════════════════════════════════════════════════════════════════════════
# Items 6 & 7 — resilience must price substitution and must not echo the target
# ════════════════════════════════════════════════════════════════════════════

def _seed_two_supplier_bom(session):
    """One BOM line with two suppliers at DIFFERENT prices and DIFFERENT distances.

    d1 is near the Memphis reference hub and cheapest; d2 is far and dearer. Losing
    d1 must therefore cost real money and real days — the case that used to report
    cost_delta_pct 0.0 because the BOM was never re-priced.
    """
    session.add_all([
        Distributor(id=1, name="NearCheap", latitude=35.15, longitude=-90.05,
                    city="Memphis", state="TN", country="USA", is_domestic=True),
        Distributor(id=2, name="FarDear", latitude=47.6, longitude=-122.3,
                    city="Seattle", state="WA", country="USA", is_domestic=True),
    ])
    session.commit()
    session.add_all([
        Component(id=1, mpn="C1", manufacturer="M", category="Test", risk_score=0.3),
        Component(id=2, mpn="C2", manufacturer="M", category="Test", risk_score=0.3),
    ])
    session.commit()
    session.add_all([
        DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=1000, moq=1),
        DistributorOffer(id=2, component_id=1, distributor_id=2, price=25.0, stock=1000, moq=1),
        DistributorOffer(id=3, component_id=2, distributor_id=1, price=4.0, stock=1000, moq=1),
        DistributorOffer(id=4, component_id=2, distributor_id=2, price=9.0, stock=1000, moq=1),
    ])
    session.commit()


def test_distributor_failure_prices_the_substitution(db_session):
    """Losing the cheapest supplier on a fully-hedged BOM has zero FULFILLMENT
    impact — correctly — but a real COST impact. The endpoint used to report 0.0%
    because it computed the component cost once and never recomputed it."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/distributor-failure", json={
            "distributor_id": 1,
            "items": [{"component_id": 1, "quantity": 10},
                      {"component_id": 2, "quantity": 5}],
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Baseline: 10 x $10 + 5 x $4 = $120 at the cheapest offers.
        sub = data["cost_substitution"]
        assert sub["baseline_component_cost_usd"] == pytest.approx(120.0, abs=0.01)
        # Scenario: 10 x $25 + 5 x $9 = $295.
        assert sub["scenario_component_cost_usd"] == pytest.approx(295.0, abs=0.01)
        assert sub["substitution_delta_usd"] > 0
        assert sub["n_lines_repriced"] == 2
        assert data["cost_delta_pct"] > 0, "losing the cheapest supplier cost nothing"

        # ...and the zero fulfillment impact is EXPLAINED, not left as bare zeros.
        assert data["hedging"]["fully_hedged"] is True
        assert data["hedging"]["n_lines_orphaned"] == 0
        assert "fully hedged" in data["hedging"]["statement"].lower()
        assert data["affected_bom_ids"] == []
        assert data["spend_at_risk_basis"], "spend-at-risk basis not explained"
    finally:
        app.dependency_overrides.clear()


def test_orphaning_a_line_never_makes_the_bom_cheaper(db_session):
    """Re-pricing skips a line with no surviving offer, so orphaning a line used to
    DELETE its cost — losing the only supplier for a part scored as a saving."""
    db_session.add_all([
        Distributor(id=1, name="Multi", latitude=35.15, longitude=-90.05,
                    city="Memphis", state="TN", country="USA", is_domestic=True),
        Distributor(id=2, name="SoleSource", latitude=40.0, longitude=-75.0,
                    city="Philly", state="PA", country="USA", is_domestic=True),
    ])
    db_session.commit()
    db_session.add_all([
        Component(id=1, mpn="C1", manufacturer="M", category="T", risk_score=0.3),
        Component(id=2, mpn="C2", manufacturer="M", category="T", risk_score=0.3),
    ])
    db_session.commit()
    db_session.add_all([
        DistributorOffer(id=1, component_id=1, distributor_id=1, price=1.0, stock=500, moq=1),
        DistributorOffer(id=2, component_id=1, distributor_id=2, price=2.0, stock=500, moq=1),
        # c2 exists ONLY at distributor 2 — and it is the expensive part.
        DistributorOffer(id=3, component_id=2, distributor_id=2, price=90.0, stock=500, moq=1),
    ])
    db_session.commit()

    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/distributor-failure", json={
            "distributor_id": 2,
            "items": [{"component_id": 1, "quantity": 1},
                      {"component_id": 2, "quantity": 1}],
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()

        sub = data["cost_substitution"]
        assert sub["n_lines_unpriceable"] == 1
        assert sub["scenario_component_cost_usd"] >= sub["baseline_component_cost_usd"], (
            "orphaning the sole source of a $90 part was scored as a cost REDUCTION"
        )
        assert data["cost_delta_pct"] >= 0.0
        assert data["affected_bom_ids"] == [2]
        assert data["hedging"]["fully_hedged"] is False
        assert data["hedging"]["n_lines_orphaned"] == 1
    finally:
        app.dependency_overrides.clear()


def test_resilience_honours_quantity(db_session):
    """The request schema had no quantity field, so a 5,000-unit build priced
    identically to a 1-unit prototype."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)

        def _cost(qty):
            resp = client.post("/api/v1/resilience/distributor-failure", json={
                "distributor_id": 2,
                "items": [{"component_id": 1, "quantity": qty}],
            })
            assert resp.status_code == 200, resp.text
            return resp.json()

        one, hundred = _cost(1), _cost(100)
        assert hundred["baseline_cost_usd"] > one["baseline_cost_usd"] * 50
        assert hundred["total_units"] == 100
        assert one["quantity_source"] == "explicit"

        legacy = client.post("/api/v1/resilience/distributor-failure", json={
            "distributor_id": 2, "bom_component_ids": [1],
        })
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["quantity_source"] == "assumed_one_unit_per_line"
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_does_not_echo_the_target_as_the_achieved_eta(db_session):
    """Target 7d against a ~2.x-day baseline was reported as scenario_eta 7.0 and a
    +4.2-day DEGRADATION. Relaxing a satisfied constraint is not a degradation."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/delivery-target", json={
            "target_delivery_days": 60,
            "items": [{"component_id": 1, "quantity": 1}],
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["target_delivery_days"] == 60
        assert data["scenario_eta_days"] != 60.0, "the target was echoed as the ETA"
        assert data["scenario_eta_days"] == pytest.approx(data["baseline_eta_days"], abs=0.05)
        assert data["eta_delta_days"] == pytest.approx(0.0, abs=0.05)
        assert data["target_met"] is True
        assert data["target_is_binding"] is False
        assert data["eta_note"]
    finally:
        app.dependency_overrides.clear()


def test_delivery_target_reports_an_impossible_target_as_unmet(db_session):
    """Target 1d asserted scenario_eta 1.0 while fulfilment collapsed to 0.0 and
    suppliers_capable was empty — an ETA nobody could deliver."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/delivery-target", json={
            "target_delivery_days": 1,
            "items": [{"component_id": 1, "quantity": 1}],
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["suppliers_capable"] == []
        assert data["scenario_eta_days"] != 1.0, "an unmeetable target was reported as met"
        assert data["target_met"] is False
        assert data["unmet_component_ids"] == [1]
        assert "INFEASIBLE" in data["eta_note"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("endpoint,extra", [
    ("distributor-failure", {"distributor_id": 1}),
    ("geopolitical-risk", {"risk_multiplier": 2.0}),
    ("delivery-target", {"target_delivery_days": 30}),
])
def test_resilience_404s_on_unknown_component_ids(db_session, endpoint, extra):
    """An unknown id was silently treated as a line with no supplier: it counted as
    orphaned and dragged the fulfillment percentiles down, so the caller got a
    confident 200 describing a BOM it never asked about."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/v1/resilience/{endpoint}",
            json={**extra, "items": [{"component_id": 999_999, "quantity": 1}]},
        )
        assert resp.status_code == 404, resp.text
        assert "999999" in resp.text
    finally:
        app.dependency_overrides.clear()


def test_sensitivity_explains_a_flat_tornado(db_session):
    """Four levers at spread 0.0 with no explanation is indistinguishable from a
    broken endpoint. It must name the zero levers and say why."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/sensitivity", json={
            "bom_component_ids": [1, 2], "metric": "cost",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "zero_spread_levers" in data
        assert data["interpretation"], "a flat tornado was returned with no explanation"
        assert data["n_bom_lines"] == 2
    finally:
        app.dependency_overrides.clear()


def test_sensitivity_metric_is_constrained_in_the_schema(db_session):
    """`metric` accepted only cost/cvar but OpenAPI declared an unconstrained str."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/resilience/sensitivity", json={
            "bom_component_ids": [1], "metric": "nonsense",
        })
        assert resp.status_code == 422, resp.text

        schema = client.get("/openapi.json").json()
        metric = schema["components"]["schemas"]["SensitivityMetric"]
        assert set(metric["enum"]) == {"cost", "cvar"}
    finally:
        app.dependency_overrides.clear()


def test_dual_sourcing_says_when_a_bom_is_fully_hedged(db_session):
    """`entries: []` for a diversified BOM is the correct answer; it must be stated."""
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/dual-sourcing-plan", json={
            "bom_component_ids": [1, 2], "top_n": 10,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["entries"] == []
        assert data["fully_hedged"] is True
        assert data["n_bom_lines"] == 2
        assert data["n_single_source_lines"] == 0
        assert "hedged" in data["interpretation"].lower()
    finally:
        app.dependency_overrides.clear()


def test_criticality_sweep_explains_a_page_of_zeros(db_session):
    _seed_two_supplier_bom(db_session)
    app.dependency_overrides[get_db] = _override(db_session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/criticality-sweep", json={"top_n": 10})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["n_distributors_scored"] == 2
        assert data["n_distributors_with_exposure"] == 0
        assert data["n_components_in_scope"] == 2
        assert data["n_single_source_components"] == 0
        assert data["interpretation"]
        assert data["exposure_definition"]
    finally:
        app.dependency_overrides.clear()


def test_dual_sourcing_p_fail_is_not_betweenness(db_session):
    """p_fail_current was returning the min-max normalized betweenness verbatim,
    implying the largest distributors are the most likely to fail."""
    session = db_session
    session.add_all([
        Distributor(id=1, name="Sole", latitude=35.15, longitude=-90.05,
                    city="Memphis", state="TN", country="USA", is_domestic=True),
        Distributor(id=2, name="Alt", latitude=40.0, longitude=-75.0,
                    city="Philly", state="PA", country="USA", is_domestic=True),
    ])
    session.commit()
    session.add(Component(id=1, mpn="C1", manufacturer="M", category="T", risk_score=0.3))
    session.commit()
    session.add_all([
        DistributorOffer(id=1, component_id=1, distributor_id=1, price=10.0, stock=100, moq=1),
        DistributorOffer(id=2, component_id=1, distributor_id=2, price=8.0, stock=0, moq=1),
    ])
    session.commit()

    from app.graph.builder import build_graph_state
    gs = build_graph_state(session)

    app.dependency_overrides[get_db] = _override(session)
    try:
        client = TestClient(app)
        resp = client.post("/api/v1/resilience/dual-sourcing-plan", json={"top_n": 10})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["entries"], "expected the single-source line to be recommended"
        assert data["p_fail_basis"], "the probability model is not explained"

        betweenness_values = {round(v, 6) for v in gs.betweenness.values()}
        for entry in data["entries"]:
            p = entry["p_fail_current"]
            assert 0.0 < p <= 0.5, p
            assert round(p, 6) not in betweenness_values or p == pytest.approx(
                gs.p_disruption[1], abs=1e-6
            ), "p_fail is still the raw betweenness value"
            assert p == pytest.approx(
                gs.p_disruption[1], abs=1e-6
            ) or p == pytest.approx(gs.p_disruption[2], abs=1e-6)
    finally:
        app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════════════
# Item 10 — the cart must reject a quantity the optimizer cannot use
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("quantity", [-5, -1, 0, -0.5])
def test_cart_rejects_non_positive_quantity(client, auth_token, db_session, quantity):
    """`{"quantity": -5}` returned 201 Created and the -5 then flowed into the
    optimizer's demand constraint."""
    db_session.add(Distributor(id=1, name="D1", latitude=35.0, longitude=-90.0,
                               city="M", state="TN", country="USA", is_domestic=True))
    db_session.add(Component(id=1, mpn="C1", manufacturer="M", category="T", risk_score=0.3))
    db_session.commit()
    db_session.add(DistributorOffer(id=1, component_id=1, distributor_id=1,
                                    price=1.0, stock=1000, moq=1))
    db_session.commit()

    resp = client.post(
        "/api/v1/cart",
        json={"component_id": 1, "distributor_id": 1, "quantity": quantity},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 422, resp.text


def test_cart_accepts_a_positive_quantity(client, auth_token, db_session):
    db_session.add(Distributor(id=1, name="D1", latitude=35.0, longitude=-90.0,
                               city="M", state="TN", country="USA", is_domestic=True))
    db_session.add(Component(id=1, mpn="C1", manufacturer="M", category="T", risk_score=0.3))
    db_session.commit()
    db_session.add(DistributorOffer(id=1, component_id=1, distributor_id=1,
                                    price=1.0, stock=1000, moq=1))
    db_session.commit()

    resp = client.post(
        "/api/v1/cart",
        json={"component_id": 1, "distributor_id": 1, "quantity": 5},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["quantity"] == 5.0


# ════════════════════════════════════════════════════════════════════════════
# Item 11 — feeds must refresh at startup, not 15 minutes later
# ════════════════════════════════════════════════════════════════════════════

def test_feed_scheduler_runs_immediately_on_startup():
    """APScheduler's interval trigger fires one full interval AFTER the job is
    added. Render's free tier spins the service down after ~15 minutes idle, so the
    deployed process almost never survived to its first tick and all four feeds read
    `unavailable` in production."""
    from app.feeds import LiveDataCache
    from app.feeds.scheduler import build_scheduler

    scheduler = build_scheduler(LiveDataCache())
    # The scheduler is never started here — inspecting the pending job is enough, and
    # starting it would fire real network calls.
    job = scheduler.get_job("feed_refresh")
    assert job is not None, "feed_refresh job not registered"
    assert job.next_run_time is not None, (
        "feed_refresh has no next_run_time, so its first run is one full 15-minute "
        "interval after startup"
    )
    delay = job.next_run_time.replace(tzinfo=None) - datetime.now()
    assert delay < timedelta(minutes=1), (
        f"first feed refresh is {delay} away — the deployed instance will spin "
        "down before it fires"
    )
