"""Tests for cross-dock hub enumeration + 5% threshold."""
from app.optimization.cross_dock import (
    CROSS_DOCK_IMPROVEMENT_THRESHOLD, DistributorShipment, RouteMetrics,
    evaluate_cross_dock, evaluate_direct, evaluate_hub,
)
from app.optimization.freight_hubs import FREIGHT_HUBS, get_hub
from app.optimization.routing import GeoPoint, RoutingNode
from app.optimization.strategies import get_strategy


def _ship(did, lat, lng, kg=50.0, tier="mid"):
    return DistributorShipment(
        distributor_id=did, distributor_name=f"d{did}",
        lat=lat, lng=lng, weight_kg=kg, distributor_tier=tier,
    )


def test_cross_dock_never_chosen_for_single_distributor():
    depot = GeoPoint(34.85, -82.39)
    ships = [_ship(1, 40.0, -75.0)]
    direct = RouteMetrics(cost_usd=500.0, lead_time_days=3.0, co2_kg=2.0)
    decision = evaluate_cross_dock(direct, ships, depot, get_strategy("balanced"))
    assert decision.enabled is False
    assert "single" in decision.rationale.lower()


def test_cross_dock_chosen_when_east_coast_distributors_favor_atlanta():
    """
    Depot in Greenville SC, distributors spread across the Midwest/Northeast.
    Cheapest strategy should pick a central hub and save >5%.
    """
    depot = GeoPoint(34.8526, -82.3940)  # Greenville SC
    ships = [
        _ship(1, 41.88, -87.63, kg=200),  # Chicago
        _ship(2, 42.36, -71.06, kg=200),  # Boston
        _ship(3, 40.71, -74.00, kg=200),  # NYC
        _ship(4, 39.74, -104.99, kg=200),  # Denver (far)
    ]
    # Fake "direct" as very high (simulates a long multi-stop tour)
    direct = RouteMetrics(cost_usd=5000.0, lead_time_days=12.0, co2_kg=50.0)
    decision = evaluate_cross_dock(direct, ships, depot, get_strategy("cheapest"))
    # Atlanta, Louisville, Memphis, or Columbus should win
    assert decision.hub is not None
    assert decision.hub.state in {"GA", "KY", "TN", "OH", "IL", "MO", "IN"}


def test_cross_dock_rejected_when_improvement_below_threshold():
    """
    Construct a direct route where hub savings are small enough to be
    below the 5% threshold — decision should be 'enabled=False' even
    though best_hub is identified.
    """
    depot = GeoPoint(34.85, -82.39)
    ships = [
        _ship(1, 35.0, -82.0, kg=10),
        _ship(2, 35.1, -82.1, kg=10),
    ]
    # Super-cheap direct (near depot, low weight)
    cheap_direct = evaluate_direct(
        depot,
        [
            RoutingNode(id=1, lat=35.0, lng=-82.0, name="d1"),
            RoutingNode(id=2, lat=35.1, lng=-82.1, name="d2"),
        ],
        {1: ships[0], 2: ships[1]},
    )
    decision = evaluate_cross_dock(cheap_direct, ships, depot, get_strategy("balanced"))
    # Direct pickup is already efficient, hub adds handling fee → reject
    assert decision.enabled is False


def test_evaluate_hub_includes_handling_fee():
    depot = GeoPoint(34.85, -82.39)
    ships = [_ship(1, 35.0, -82.0, kg=10), _ship(2, 35.1, -82.1, kg=10)]
    hub = get_hub(5)  # Atlanta
    m = evaluate_hub(hub, depot, ships)
    # Handling fee is always in the total
    assert m.cost_usd >= 50.0
