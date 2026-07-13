"""
Unit tests for the greedy sourcing baselines (app.optimization.greedy).

These baselines exist to honestly benchmark solve_sourcing's CP-SAT MILP, so
the key invariant tested here is that landed_cost_breakdown scores every
solver (greedy, greedy+ADD, and the real MILP) with the exact same cost
model — same _freight_model_by_did helper, same PRICE_SCALE, same
consolidation_bonus_usd sign convention — so no comparison is rigged.
"""
import pytest

from app.optimization.constants import (
    KM_PER_MILE,
    LBS_PER_KG,
    CWT_PER_LB,
    LTL_BASE_FEE_USD,
    LTL_RATE_USD_PER_CWT_MILE,
)
from app.optimization.sourcing import AVG_KG_PER_UNIT
from app.optimization.greedy import (
    landed_cost_breakdown,
    solve_sourcing_greedy,
    solve_sourcing_greedy_add,
)
from app.optimization.sourcing import BomLine, Offer, SourcingAssignment, solve_sourcing
from app.optimization.strategies import get_strategy


def _offer(cid, did, price, stock=1000, moq=1, domestic=True, name=None, km=0.0):
    return Offer(
        component_id=cid, distributor_id=did, price_usd=price,
        stock=stock, moq=moq, is_domestic=domestic,
        distributor_name=name or f"dist_{did}",
        dist_km_from_depot=km,
    )


# ── solve_sourcing_greedy: myopic per-line cheapest picker ──────────────────

def test_greedy_picks_cheapest_offer_when_stock_available():
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        _offer(1, 1, 0.49), _offer(1, 2, 1.20), _offer(1, 3, 2.00),
    ]
    result = solve_sourcing_greedy(bom, offers, get_strategy("cheapest"))
    assert len(result.assignments) == 1
    assert result.assignments[0].distributor_id == 1
    assert result.assignments[0].unit_price_usd == 0.49
    assert result.assignments[0].quantity == 10
    assert result.status == "GREEDY"


def test_greedy_rejects_international_when_us_only_true():
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        _offer(1, 1, 0.25, domestic=False),  # cheaper, but foreign
        _offer(1, 2, 1.00, domestic=True),
    ]
    result = solve_sourcing_greedy(bom, offers, get_strategy("cheapest"), us_only=True)
    assert len(result.assignments) == 1
    assert result.assignments[0].distributor_id == 2
    assert result.assignments[0].unit_price_usd == 1.00


def test_greedy_skips_offer_with_insufficient_moq_stock_in_favor_of_feasible():
    # offer1 is cheapest but its stock (500) can't cover its own MOQ (1000)
    # for this 5-unit line, so it must be excluded even though a feasible
    # (pricier) offer exists.
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=5)]
    offers = [
        _offer(1, 1, 0.30, stock=500, moq=1000),   # infeasible: stock < moq
        _offer(1, 2, 1.00, stock=100, moq=1),      # feasible
    ]
    result = solve_sourcing_greedy(bom, offers, get_strategy("cheapest"))
    assert len(result.assignments) == 1
    assert result.assignments[0].distributor_id == 2
    assert result.assignments[0].unit_price_usd == 1.00


def test_greedy_raises_same_valueerror_as_milp_when_line_has_no_offers():
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=5),
        BomLine(component_id=2, mpn="PART-B", quantity=5),
    ]
    offers = [_offer(1, 1, 1.00)]  # no offers at all for component_id=2

    with pytest.raises(ValueError) as greedy_exc:
        solve_sourcing_greedy(bom, offers, get_strategy("cheapest"))
    with pytest.raises(ValueError) as milp_exc:
        solve_sourcing(bom, offers, get_strategy("cheapest"))

    assert str(greedy_exc.value) == str(milp_exc.value)
    assert "PART-B" in str(greedy_exc.value)


# ── landed_cost_breakdown: hand-computed 2-line fixture ─────────────────────

def test_landed_cost_breakdown_matches_hand_computation():
    # Two lines, qty=10 each, unit-cheapest offers scattered across two
    # distributors (D1 for line A, D2 for line B) — both distributors 100km
    # from depot, both domestic.
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=10),
        BomLine(component_id=2, mpn="PART-B", quantity=10),
    ]
    offers = [
        _offer(1, 1, 1.00, name="D1", km=100.0),
        _offer(1, 2, 1.20, name="D2", km=100.0),
        _offer(2, 1, 1.20, name="D1", km=100.0),
        _offer(2, 2, 1.00, name="D2", km=100.0),
    ]
    assignments = [
        SourcingAssignment(component_id=1, mpn="PART-A", distributor_id=1,
                            distributor_name="D1", quantity=10, unit_price_usd=1.00),
        SourcingAssignment(component_id=2, mpn="PART-B", distributor_id=2,
                            distributor_name="D2", quantity=10, unit_price_usd=1.00),
    ]
    weights = get_strategy("cheapest")  # transport_penalty_scale=1.0, consolidation_bonus_usd=0.5

    # Hand computation, mirroring _freight_model_by_did's LTL decomposition exactly:
    #   fixed[d]    = LTL_BASE_FEE_USD                              (per OPENED distributor)
    #   per_unit[d] = AVG_KG_PER_UNIT * LBS_PER_KG * CWT_PER_LB
    #                 * miles * LTL_RATE_USD_PER_CWT_MILE           (per UNIT shipped from d)
    # Both D1 and D2 are 100 km away -> identical rates. D1 ships 10 units,
    # D2 ships 10 units, so 20 units of variable freight are charged IN TOTAL —
    # not 2 x a full-BOM shipment.
    miles = 100.0 / KM_PER_MILE
    per_unit = AVG_KG_PER_UNIT * LBS_PER_KG * CWT_PER_LB * miles * LTL_RATE_USD_PER_CWT_MILE

    expected_component_cost = 10 * 1.00 + 10 * 1.00          # = 20.0
    expected_transport_fixed = 2 * LTL_BASE_FEE_USD          # 2 distinct distributors
    expected_transport_variable = 20 * per_unit              # 20 units shipped in total
    expected_consolidation_charge = 2 * weights.consolidation_bonus_usd
    expected_total = (
        expected_component_cost
        + expected_transport_fixed
        + expected_transport_variable
        + expected_consolidation_charge
    )

    breakdown = landed_cost_breakdown(assignments, offers, bom, weights)

    assert breakdown["component_cost"] == pytest.approx(expected_component_cost)
    assert breakdown["transport_fixed"] == pytest.approx(expected_transport_fixed)
    assert breakdown["transport_variable"] == pytest.approx(expected_transport_variable)
    assert breakdown["total_cost"] == pytest.approx(expected_total)
    assert breakdown["consolidation_charge"] == pytest.approx(expected_consolidation_charge)
    assert breakdown["n_distinct_suppliers"] == 2

    # Pin the actual magnitudes, so a silently-rescaled freight model is caught:
    #   per_unit = 0.05 * 2.20462 * 0.01 * (100/1.60934) * 0.43 = $0.0294527/unit
    assert per_unit == pytest.approx(0.0294527, abs=1e-6)
    assert breakdown["transport_fixed"] == pytest.approx(150.0)      # 2 x $75
    assert breakdown["transport_variable"] == pytest.approx(0.58905, abs=1e-4)
    assert breakdown["total_cost"] == pytest.approx(171.589, abs=1e-2)


# ── The freight-allocation fix: variable freight is allocated, not replicated ──

def _split_fixture(n_suppliers: int, qty_per_line: int = 100):
    """n BOM lines, each single-sourced to its own distributor, all 200 km out."""
    bom = [
        BomLine(component_id=i, mpn=f"PART-{i}", quantity=qty_per_line)
        for i in range(1, n_suppliers + 1)
    ]
    offers = [
        _offer(i, d, 1.00, name=f"D{d}", km=200.0)
        for i in range(1, n_suppliers + 1)
        for d in range(1, n_suppliers + 1)
    ]
    assignments = [
        SourcingAssignment(component_id=i, mpn=f"PART-{i}", distributor_id=i,
                           distributor_name=f"D{i}", quantity=qty_per_line,
                           unit_price_usd=1.00)
        for i in range(1, n_suppliers + 1)
    ]
    return bom, offers, assignments


def test_variable_freight_is_allocated_across_suppliers_not_replicated():
    """
    THE BUG THIS PINS: the old model charged every opened distributor a full
    representative-BOM shipment weight, so splitting the same total units across
    N suppliers multiplied variable freight by N. Corrected, total variable
    freight depends only on TOTAL UNITS SHIPPED (all distributors here are
    equidistant), not on how many suppliers are opened.
    """
    weights = get_strategy("cheapest")

    # Hold total units constant at 600 while varying how many suppliers ship them.
    variable_by_n = {}
    for n, qty in ((1, 600), (2, 300), (3, 200), (6, 100)):
        bom, offers, assignments = _split_fixture(n, qty_per_line=qty)
        bd = landed_cost_breakdown(assignments, offers, bom, weights)
        assert bd["n_distinct_suppliers"] == n
        variable_by_n[n] = bd["transport_variable"]

    miles = 200.0 / KM_PER_MILE
    per_unit = AVG_KG_PER_UNIT * LBS_PER_KG * CWT_PER_LB * miles * LTL_RATE_USD_PER_CWT_MILE
    expected = 600 * per_unit

    for n, var in variable_by_n.items():
        assert var == pytest.approx(expected), (
            f"variable freight for {n} suppliers = {var}, expected {expected} "
            "— it must depend on total units shipped, not on supplier count"
        )


def test_fixed_freight_still_scales_with_supplier_count():
    """The per-visit fixed charge is REAL fixed-charge economics and must not
    regress — opening N distributors costs N x LTL_BASE_FEE_USD."""
    weights = get_strategy("cheapest")
    for n, qty in ((1, 600), (2, 300), (3, 200), (6, 100)):
        bom, offers, assignments = _split_fixture(n, qty_per_line=qty)
        bd = landed_cost_breakdown(assignments, offers, bom, weights)
        assert bd["transport_fixed"] == pytest.approx(n * LTL_BASE_FEE_USD)
        assert bd["consolidation_charge"] == pytest.approx(
            n * weights.consolidation_bonus_usd
        )


def test_per_unit_freight_scales_linearly_with_quantity():
    """Variable freight is proportional to units shipped (it used to be flat in
    quantity per supplier, which is what let it be replicated for free)."""
    weights = get_strategy("cheapest")
    bom_a, offers_a, asg_a = _split_fixture(2, qty_per_line=100)
    bom_b, offers_b, asg_b = _split_fixture(2, qty_per_line=1000)
    var_a = landed_cost_breakdown(asg_a, offers_a, bom_a, weights)["transport_variable"]
    var_b = landed_cost_breakdown(asg_b, offers_b, bom_b, weights)["transport_variable"]
    assert var_b == pytest.approx(10.0 * var_a)


# ── Anti-rigging invariant: MILP objective == landed_cost_breakdown total ────

def test_milp_objective_equals_landed_cost_breakdown(monkeypatch):
    """
    The single invariant that keeps the benchmark honest: the cost the solver
    MINIMIZES and the cost the benchmark SCORES with must be the same function.
    Solve a small instance, then re-score the solver's own answer with
    landed_cost_breakdown and require agreement with its objective value.
    """
    # Neutralise the optional ML / live-feed surcharges, which enter the MILP
    # objective but are not part of the landed-cost benchmark model.
    monkeypatch.setattr("app.ml.get_ml_state", lambda: None)
    monkeypatch.setattr("app.feeds.get_live_data_cache", lambda: None)

    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=40),
        BomLine(component_id=2, mpn="PART-B", quantity=25),
        BomLine(component_id=3, mpn="PART-C", quantity=60),
    ]
    offers = [
        _offer(1, 1, 1.00, name="D1", km=120.0),
        _offer(1, 2, 1.15, name="D2", km=900.0),
        _offer(2, 1, 1.30, name="D1", km=120.0),
        _offer(2, 2, 1.00, name="D2", km=900.0),
        _offer(3, 1, 1.05, name="D1", km=120.0),
        _offer(3, 2, 1.02, name="D2", km=900.0),
    ]
    weights = get_strategy("cheapest")

    result = solve_sourcing(bom, offers, weights, us_only=True)
    assert result.objective_usd is not None

    bd = landed_cost_breakdown(result.assignments, offers, bom, weights)

    # Agreement to within the objective's integer rounding (milli-cents).
    assert bd["total_cost"] == pytest.approx(result.objective_usd, abs=0.01), (
        f"solver minimized {result.objective_usd} but the benchmark scores the "
        f"same plan at {bd['total_cost']} — the two arms are being judged by "
        "different cost models"
    )


# ── solve_sourcing_greedy_add: consolidation beats scattered per-line cheapest ─

def _scattered_consolidation_fixture():
    # Line A's cheapest offer is at D1 (1.00 vs D2's 1.20); line B's cheapest
    # offer is at D2 (1.00 vs D1's 1.20). Naive per-line greedy therefore
    # scatters across both distributors, paying two ~$75 LTL fixed charges.
    # Consolidating onto a single distributor (accepting the +$0.20/unit
    # premium on one line) saves an entire ~$75 distributor visit, which
    # dominates the small component-cost premium.
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=10),
        BomLine(component_id=2, mpn="PART-B", quantity=10),
    ]
    offers = [
        _offer(1, 1, 1.00, name="D1", km=100.0),
        _offer(1, 2, 1.20, name="D2", km=100.0),
        _offer(2, 1, 1.20, name="D1", km=100.0),
        _offer(2, 2, 1.00, name="D2", km=100.0),
    ]
    return bom, offers


def test_greedy_scatters_across_two_distributors():
    bom, offers = _scattered_consolidation_fixture()
    result = solve_sourcing_greedy(bom, offers, get_strategy("cheapest"))
    dids = {a.distributor_id for a in result.assignments}
    assert dids == {1, 2}
    breakdown = landed_cost_breakdown(result.assignments, offers, bom, get_strategy("cheapest"))
    assert breakdown["n_distinct_suppliers"] == 2


def test_greedy_add_consolidates_and_reduces_total_cost():
    bom, offers = _scattered_consolidation_fixture()
    weights = get_strategy("cheapest")

    greedy_result = solve_sourcing_greedy(bom, offers, weights)
    add_result = solve_sourcing_greedy_add(bom, offers, weights)

    greedy_breakdown = landed_cost_breakdown(greedy_result.assignments, offers, bom, weights)
    add_breakdown = landed_cost_breakdown(add_result.assignments, offers, bom, weights)

    assert greedy_breakdown["n_distinct_suppliers"] == 2
    assert add_breakdown["n_distinct_suppliers"] == 1
    assert add_breakdown["total_cost"] < greedy_breakdown["total_cost"]
    assert add_result.status == "GREEDY_ADD"


# ── Invariant: the real MILP must never do worse than either greedy baseline ─

def test_milp_total_landed_cost_never_exceeds_greedy_on_varied_fixture():
    # 4 BOM lines, offers at 3 distributors with meaningfully different
    # distances (hence different fixed transport costs) and near-tied unit
    # prices, so naive per-line-cheapest scatters across all 3 distributors
    # while the MILP should consolidate onto whichever subset is cheapest
    # once fixed transport + consolidation charges are counted.
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=10),
        BomLine(component_id=2, mpn="PART-B", quantity=10),
        BomLine(component_id=3, mpn="PART-C", quantity=10),
        BomLine(component_id=4, mpn="PART-D", quantity=10),
    ]
    offers = [
        # component 1: cheapest at D1
        _offer(1, 1, 1.00, name="D1", km=100.0),
        _offer(1, 2, 1.10, name="D2", km=150.0),
        _offer(1, 3, 1.05, name="D3", km=400.0),
        # component 2: cheapest at D2
        _offer(2, 1, 1.10, name="D1", km=100.0),
        _offer(2, 2, 1.00, name="D2", km=150.0),
        _offer(2, 3, 1.08, name="D3", km=400.0),
        # component 3: cheapest at D3
        _offer(3, 1, 1.05, name="D1", km=100.0),
        _offer(3, 2, 1.08, name="D2", km=150.0),
        _offer(3, 3, 1.00, name="D3", km=400.0),
        # component 4: cheapest at D1 (tie-breaker toward D1)
        _offer(4, 1, 1.00, name="D1", km=100.0),
        _offer(4, 2, 1.02, name="D2", km=150.0),
        _offer(4, 3, 1.01, name="D3", km=400.0),
    ]
    weights = get_strategy("cheapest")

    greedy_result = solve_sourcing_greedy(bom, offers, weights, us_only=True)
    milp_result = solve_sourcing(bom, offers, weights, us_only=True)

    greedy_breakdown = landed_cost_breakdown(greedy_result.assignments, offers, bom, weights)
    milp_breakdown = landed_cost_breakdown(milp_result.assignments, offers, bom, weights)

    # Naive greedy scatters across all 3 distributors (cheapest-per-line).
    assert greedy_breakdown["n_distinct_suppliers"] == 3
    # The MILP must score at least as well as the naive baseline once both
    # are scored with the identical landed-cost model.
    assert milp_breakdown["total_cost"] <= greedy_breakdown["total_cost"]
