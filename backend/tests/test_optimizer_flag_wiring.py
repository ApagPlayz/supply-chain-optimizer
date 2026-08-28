"""
`us_only` and `graph_aware` must actually move the answer — not merely be accepted.

WHY THIS FILE EXISTS
--------------------
Both flags existed on `VrpRequest` and were plumbed through `optimize_bom` ->
`solve_sourcing`, but `frontend/src/services/api.ts` posted NO BODY to
`POST /optimize/vrp`, so every plan the live site has ever shown was solved at
`us_only=False, graph_aware=False`. The frontend now sends them, and the tests
below are the guard that sending them means something: each one runs the SAME
BOM twice, flipping one flag, and asserts the solver picks a DIFFERENT supplier
and charges a different price. A test that only asserted "HTTP 200" would have
passed for the entire period the flags were dead.

TWO THINGS THAT ARE NOT WHAT THEY LOOK LIKE, both pinned by tests here:

1. `us_only` can only move the `cheapest` strategy. `fastest`, `greenest` and
   `balanced` are ALREADY `us_only_sourcing=True` in `strategies.py`, and
   `solve.py:464` ORs the request flag with the strategy's own. So the honest
   label is "the one globally-sourced strategy stops sourcing globally", not
   "the whole page switches to domestic".

2. Because those three strategies are already domestic-only, `us_only=True`
   CANNOT empty a supplier pool that the default run had not already emptied:
   a BOM line with no US offer fails the default run too. On this endpoint the
   empty-pool 400 is a property of the cart, not of the toggle — which is why
   the UI must not blame the toggle for it.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.models.order import CartItem
from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer


DEPOT = GeoPoint(lat=30.2672, lng=-97.7431)  # Austin, TX — the seeded depot


def _offer(cid: int, did: int, price: float, *, domestic: bool, km: float = 400.0) -> Offer:
    """Two offers that differ ONLY in price and the field under test."""
    return Offer(
        component_id=cid,
        distributor_id=did,
        distributor_name=f"dist_{did}",
        price_usd=price,
        stock=10_000,
        moq=1,
        is_domestic=domestic,
        dist_km_from_depot=km,
        risk_score=0.20,
        is_chinese_origin=False,
        distributor_country="USA" if domestic else "SGP",
    )


def _meta(did: int, *, domestic: bool) -> DistributorMeta:
    # Both distributors sit at the same point so the pickup tour, its distance and
    # its CO2e are identical for either choice: any difference in the returned plan
    # is the sourcing MILP's, not the router's.
    return DistributorMeta(
        id=did, name=f"dist_{did}", lat=32.7767, lng=-96.7970,
        city="Dallas", state="TX", country="USA" if domestic else "Singapore",
        is_domestic=domestic, tier="major",
    )


def _cheapest(response) -> object:
    return next(a for a in response.alternatives if a.id == "cheapest")


def _sole_supplier(alternative) -> int:
    """The distributor the plan actually buys from (route stop 0 is a supplier)."""
    assert alternative.sourcing, "alternative carries no sourcing assignments"
    dids = {s.distributor_id for s in alternative.sourcing}
    assert len(dids) == 1, f"expected a single-supplier plan, got {dids}"
    return dids.pop()


# ── us_only ──────────────────────────────────────────────────────────────────

def test_us_only_forces_the_global_strategy_onto_a_domestic_supplier():
    """
    `cheapest` is the one strategy defined with `us_only_sourcing=False`
    (`strategies.py:45`), so it is the only one the request-level override can
    change. `solve.py:464` ORs the two together — this proves that OR is live.

    Quantity is 1,000 on purpose. The offshore distributor pays an air-consignment
    minimum that is charged ONCE, so on a 100-unit line that fixed charge swamps a
    $0.40/unit price gap and the "global" strategy buys domestic anyway — at 1,000
    units the price gap dominates and the offshore offer genuinely wins, which is
    the only state in which turning the flag on can be seen to do anything.
    """
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=1000)]
    offers = [
        _offer(1, 1, 1.00, domestic=False),   # cheaper, offshore
        _offer(1, 2, 1.40, domestic=True),    # dearer, domestic
    ]
    distributors = {1: _meta(1, domestic=False), 2: _meta(2, domestic=True)}

    off = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, us_only=False))
    on = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, us_only=True))

    # The flag changes WHICH SUPPLIER IS BOUGHT FROM, not just the response shape.
    assert _sole_supplier(off) == 1, "default run should take the cheaper offshore offer"
    assert _sole_supplier(on) == 2, "us_only=True must exclude the offshore offer entirely"

    # And it changes the price the user is quoted: 1,000 x $1.00 vs 1,000 x $1.40.
    assert on.total_component_cost_usd > off.total_component_cost_usd
    assert off.total_component_cost_usd == 1000.0
    assert on.total_component_cost_usd == 1400.0

    # The three already-domestic strategies are untouched by the flag — the same
    # plan before and after. This is what stops the UI claiming the toggle
    # "switches the page to domestic sourcing".
    def _by_id(resp):
        return {a.id: a.total_component_cost_usd for a in resp.alternatives}
    before = _by_id(optimize_bom(bom, offers, distributors, DEPOT, us_only=False))
    after = _by_id(optimize_bom(bom, offers, distributors, DEPOT, us_only=True))
    for sid in ("fastest", "greenest", "balanced"):
        assert before[sid] == after[sid], f"{sid} is already domestic-only; the flag must not move it"
    assert before["cheapest"] != after["cheapest"]


def test_us_only_true_is_the_only_difference_between_the_two_runs():
    """Same call twice with the same flag is deterministic — so the delta above is the flag."""
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=1000)]
    offers = [_offer(1, 1, 1.00, domestic=False), _offer(1, 2, 1.40, domestic=True)]
    distributors = {1: _meta(1, domestic=False), 2: _meta(2, domestic=True)}

    a = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, us_only=True))
    b = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, us_only=True))
    assert _sole_supplier(a) == _sole_supplier(b)
    assert a.total_component_cost_usd == b.total_component_cost_usd


# ── graph_aware ──────────────────────────────────────────────────────────────

def test_graph_aware_moves_the_plan_off_the_high_betweenness_supplier(monkeypatch):
    """
    `sourcing.py:859` only adds the graph surcharge terms when `graph_aware` is
    True AND a GraphState is loaded. `solve_sourcing` reads exactly one attribute
    off that state (`_gs.betweenness`), so a stub carrying that dict is enough to
    exercise the real objective term without building the whole bipartite graph.

    Numbers: dist 1 is $1.00 with betweenness 0.80; dist 2 is $1.05 with 0.0.
    `_graph_surcharge_obj_units` prices dist 1's recourse at
    (next-cheapest gap $0.05) + (EMERGENCY_REPROCURE_PREMIUM 0.15 x $1.00) = $0.20,
    weighted by 0.80 -> $0.16/unit. $1.00 + $0.16 > $1.05, so the surcharge — and
    only the surcharge — flips the choice.
    """
    stub = SimpleNamespace(betweenness={1: 0.80, 2: 0.0})
    monkeypatch.setattr("app.graph.get_graph_state", lambda: stub)

    bom = [BomLine(component_id=1, mpn="PART-A", quantity=100)]
    offers = [
        _offer(1, 1, 1.00, domestic=True),   # cheaper, highly central
        _offer(1, 2, 1.05, domestic=True),   # dearer, peripheral
    ]
    distributors = {1: _meta(1, domestic=True), 2: _meta(2, domestic=True)}

    off = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, graph_aware=False))
    on = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, graph_aware=True))

    assert _sole_supplier(off) == 1, "without the surcharge the solver takes the cheaper price"
    assert _sole_supplier(on) == 2, "graph_aware=True must price dist 1's centrality in"

    # The surcharge is an OBJECTIVE term, not a charge: the user is quoted the real
    # price of the plan the surcharge selected, which here is genuinely dearer.
    assert off.total_component_cost_usd == 100.0
    assert on.total_component_cost_usd == 105.0


def test_graph_aware_is_inert_when_no_graph_state_is_loaded(monkeypatch):
    """
    The honest caveat the UI prints: with no GraphState the flag changes nothing.
    Guards against someone "fixing" the silent fallback into a crash, and against
    the label over-promising.
    """
    monkeypatch.setattr("app.graph.get_graph_state", lambda: None)

    bom = [BomLine(component_id=1, mpn="PART-A", quantity=100)]
    offers = [_offer(1, 1, 1.00, domestic=True), _offer(1, 2, 1.05, domestic=True)]
    distributors = {1: _meta(1, domestic=True), 2: _meta(2, domestic=True)}

    off = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, graph_aware=False))
    on = _cheapest(optimize_bom(bom, offers, distributors, DEPOT, graph_aware=True))
    assert _sole_supplier(on) == _sole_supplier(off) == 1
    assert on.total_component_cost_usd == off.total_component_cost_usd


# ── the request body actually reaches the solver ─────────────────────────────

def _seed_cart(db_session, *, domestic_offer: bool) -> None:
    db_session.add_all([
        Distributor(id=1, name="Offshore Co", latitude=1.35, longitude=103.8,
                    city="Singapore", state=None, country="Singapore",
                    is_domestic=False, total_offers=700),
        Distributor(id=2, name="Domestic Co", latitude=32.77, longitude=-96.79,
                    city="Dallas", state="TX", country="USA",
                    is_domestic=True, total_offers=900),
    ])
    db_session.add(Component(id=1, mpn="PART-A", manufacturer="M",
                             category="Resistor", risk_score=0.20))
    db_session.add(DistributorOffer(id=1, component_id=1, distributor_id=1,
                                    price=1.00, stock=10_000, moq=1))
    if domestic_offer:
        db_session.add(DistributorOffer(id=2, component_id=1, distributor_id=2,
                                        price=1.40, stock=10_000, moq=1))
    db_session.commit()

    from app.models.user import User
    user_id = db_session.query(User).filter(User.email == "test@example.com").one().id
    db_session.add(CartItem(user_id=user_id, component_id=1, distributor_id=1,
                            quantity=100, unit_price=1.00))
    db_session.commit()


def test_vrp_endpoint_hands_both_flags_to_the_solver(client, db_session, auth_token, monkeypatch):
    """
    The defect this whole change fixes: the endpoint parsed the flags and the
    frontend never sent them. Spy on `optimize_bom` and read the kwargs it was
    actually called with.
    """
    _seed_cart(db_session, domestic_offer=True)
    seen: dict = {}

    def _spy(bom, offers, distributors_meta, depot, **kwargs):
        seen.update(kwargs)
        raise ValueError("captured")  # the endpoint turns this into a 400

    monkeypatch.setattr("app.api.optimize.optimize_bom", _spy)
    headers = {"Authorization": f"Bearer {auth_token}"}

    client.post("/api/v1/optimize/vrp", json={}, headers=headers)
    assert seen["us_only"] is False and seen["graph_aware"] is False, \
        "an empty body must keep the historical defaults — nothing published may move"

    seen.clear()
    client.post("/api/v1/optimize/vrp",
                json={"us_only": True, "graph_aware": True}, headers=headers)
    assert seen["us_only"] is True and seen["graph_aware"] is True


def test_an_empty_domestic_pool_is_a_400_naming_the_part_with_the_flag_off_TOO(
    client, db_session, auth_token
):
    """
    The failure the page has to render — and the correction to the brief that
    prompted it.

    PART-A's only offer is offshore, so the domestic pool for that line is empty.
    `us_only=True` returns 400 with the MPN in the detail (not a 500, not a blank
    plan) — but so does `us_only=False`, because `fastest`, `greenest` and
    `balanced` already filter to domestic suppliers. On `/optimize/vrp` the empty
    -pool failure therefore cannot be *caused* by the toggle: it is a fact about
    the cart. The UI's message must say what the server said and must not tell the
    user the toggle broke it.
    """
    _seed_cart(db_session, domestic_offer=False)
    headers = {"Authorization": f"Bearer {auth_token}"}

    for body in ({"us_only": False}, {"us_only": True}):
        resp = client.post("/api/v1/optimize/vrp", json=body, headers=headers)
        assert resp.status_code == 400, f"{body} -> {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"]
        assert "No valid offers" in detail
        assert "PART-A" in detail


def test_a_cart_with_a_domestic_offer_solves_under_both_flag_settings(
    client, db_session, auth_token
):
    """The 400 above is the empty pool, not the flag: add a domestic offer and both succeed."""
    _seed_cart(db_session, domestic_offer=True)
    headers = {"Authorization": f"Bearer {auth_token}"}

    for body in ({}, {"us_only": True}, {"graph_aware": True},
                 {"us_only": True, "graph_aware": True}):
        resp = client.post("/api/v1/optimize/vrp", json=body, headers=headers)
        assert resp.status_code == 200, f"{body} -> {resp.status_code}: {resp.text}"
        assert len(resp.json()["alternatives"]) == 4
