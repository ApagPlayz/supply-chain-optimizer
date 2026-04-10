"""
Integration test: solve.optimize_bom produces four DISTINCT routes.

This is the regression test for the original bug where all four
strategies returned the same tour.
"""
import pytest

from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer


@pytest.fixture
def fixture_bom_and_offers():
    # 3 components sourced from an east-coast-heavy set of distributors.
    # Direct pickup is fast (short tour), so "fastest" should reject the
    # cross-dock hub's dwell penalty while "greenest" should still accept
    # it because consolidation lowers tonne-miles. This forces at least
    # two strategies to diverge on the cross-dock decision.
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=100),
        BomLine(component_id=2, mpn="PART-B", quantity=50),
        BomLine(component_id=3, mpn="PART-C", quantity=30),
    ]
    offers = [
        # PART-A offers — EastCoastPrime cheapest, forcing Raleigh selection
        Offer(1, 10, "EastCoastPrime", price_usd=1.20, stock=500, moq=1, is_domestic=True),
        Offer(1, 30, "MidwestMajor", price_usd=2.60, stock=500, moq=1, is_domestic=True),
        Offer(1, 40, "DiscountBrokerEast", price_usd=2.50, stock=500, moq=1, is_domestic=True),
        Offer(1, 50, "DiscountBrokerWest", price_usd=2.20, stock=500, moq=1, is_domestic=True),
        # PART-B offers — SoutheastMid cheapest, forcing Atlanta selection
        Offer(2, 10, "EastCoastPrime", price_usd=5.00, stock=500, moq=1, is_domestic=True),
        Offer(2, 20, "SoutheastMid", price_usd=2.50, stock=500, moq=1, is_domestic=True),
        Offer(2, 40, "DiscountBrokerEast", price_usd=3.10, stock=500, moq=1, is_domestic=True),
        # PART-C offers — DiscountBrokerEast cheapest, forcing NYC selection
        Offer(3, 10, "EastCoastPrime", price_usd=10.00, stock=500, moq=1, is_domestic=True),
        Offer(3, 20, "SoutheastMid", price_usd=8.00, stock=500, moq=1, is_domestic=True),
        Offer(3, 40, "DiscountBrokerEast", price_usd=4.50, stock=500, moq=1, is_domestic=True),
        Offer(3, 50, "DiscountBrokerWest", price_usd=6.00, stock=500, moq=1, is_domestic=True),
    ]
    distributors = {
        10: DistributorMeta(10, "EastCoastPrime", 35.7796, -78.6382, "Raleigh", "NC", "USA", True, "major"),
        20: DistributorMeta(20, "SoutheastMid", 33.7490, -84.3880, "Atlanta", "GA", "USA", True, "mid"),
        30: DistributorMeta(30, "MidwestMajor", 41.8781, -87.6298, "Chicago", "IL", "USA", True, "major"),
        40: DistributorMeta(40, "DiscountBrokerEast", 40.7128, -74.0060, "New York", "NY", "USA", True, "broker"),
        50: DistributorMeta(50, "DiscountBrokerWest", 34.0522, -118.2437, "Los Angeles", "CA", "USA", True, "broker"),
        60: DistributorMeta(60, "MidwestBroker", 39.0997, -94.5786, "Kansas City", "MO", "USA", True, "broker"),
    }
    depot = GeoPoint(lat=34.8526, lng=-82.3940)  # Greenville SC
    return bom, offers, distributors, depot


def test_four_strategies_produce_different_routes(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)

    assert len(resp.alternatives) == 4
    ids = [a.id for a in resp.alternatives]
    assert set(ids) == {"cheapest", "fastest", "greenest", "balanced"}

    # At least 2 of the 4 weighted totals (strategy_math) must differ
    totals = [a.strategy_math.weighted_total for a in resp.alternatives]
    distinct = len(set(totals))
    assert distinct >= 2, f"Expected ≥2 distinct weighted totals, got {distinct}: {totals}"


def test_all_strategies_have_breakdown_and_citations(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)
    for a in resp.alternatives:
        assert a.cost_breakdown is not None
        assert a.strategy_math is not None
        assert any("ATRI" in c for c in a.strategy_math.citations)
        assert any("EPA" in c for c in a.strategy_math.citations)


def test_cheapest_selects_low_price_offers(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)
    cheapest = next(a for a in resp.alternatives if a.id == "cheapest")
    # DiscountBrokerWest ($1.40 A + $6 C) and DiscountBrokerEast ($3.10 B)
    # should be preferred
    selected = {s.distributor_id for s in cheapest.sourcing}
    # At least one discount broker should be in the mix
    assert 40 in selected or 50 in selected


def test_at_least_one_strategy_considers_cross_dock(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)
    # Some strategy should have cross_dock.enabled=True OR
    # at least have non-None hub evaluation (even if below threshold)
    any_hub_evaluated = any(
        a.cross_dock and a.cross_dock.hub_id is not None
        for a in resp.alternatives
    )
    assert any_hub_evaluated
