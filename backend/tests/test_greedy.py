"""
Unit tests for the greedy sourcing baselines (app.optimization.greedy).

These baselines exist to honestly benchmark solve_sourcing's CP-SAT MILP, so
the key invariant tested here is that landed_cost_breakdown scores every
solver (greedy, greedy+ADD, and the real MILP) with the exact same cost
model — same _transport_cost_by_did helper, same PRICE_SCALE, same
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

    # Hand computation, mirroring _transport_cost_by_did's LTL formula exactly:
    #   avg_demand = (10 + 10) / 2 = 10 units  ->  avg_weight_kg = 10 * 0.05 = 0.5 kg
    #   miles = 100 km / KM_PER_MILE
    #   cwt   = 0.5 kg * LBS_PER_KG * CWT_PER_LB
    #   per_distributor_cost = LTL_BASE_FEE_USD + cwt * miles * LTL_RATE_USD_PER_CWT_MILE
    # Both D1 and D2 are 100km away -> identical per-distributor cost.
    avg_weight_kg = 10 * 0.05
    miles = 100.0 / KM_PER_MILE
    cwt = avg_weight_kg * LBS_PER_KG * CWT_PER_LB
    per_distributor_cost = LTL_BASE_FEE_USD + cwt * miles * LTL_RATE_USD_PER_CWT_MILE

    expected_component_cost = 10 * 1.00 + 10 * 1.00          # = 20.0
    expected_transport_fixed = 2 * per_distributor_cost        # 2 distinct distributors
    expected_consolidation_charge = 2 * weights.consolidation_bonus_usd
    expected_total = (
        expected_component_cost + expected_transport_fixed + expected_consolidation_charge
    )

    breakdown = landed_cost_breakdown(assignments, offers, bom, weights)

    assert breakdown["component_cost"] == pytest.approx(expected_component_cost)
    assert breakdown["transport_fixed"] == pytest.approx(expected_transport_fixed)
    assert breakdown["consolidation_charge"] == pytest.approx(expected_consolidation_charge)
    assert breakdown["total_cost"] == pytest.approx(expected_total)
    assert breakdown["n_distinct_suppliers"] == 2


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
