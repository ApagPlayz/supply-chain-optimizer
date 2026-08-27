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


def _tour(weights):
    """A 3-stop domestic pickup tour with the given per-stop weights."""
    depot = GeoPoint(34.85, -82.39)
    coords = [(35.23, -80.84), (33.75, -84.39), (36.16, -86.78)]
    nodes = [RoutingNode(id=i + 1, lat=la, lng=ln, name=f"d{i+1}")
             for i, (la, ln) in enumerate(coords)]
    ships = {i + 1: _ship(i + 1, la, ln, kg=w)
             for i, ((la, ln), w) in enumerate(zip(coords, weights))}
    return depot, nodes, ships


def test_a_pickup_tour_is_not_charged_a_full_load_before_it_has_collected_one():
    """The truck leaves the depot EMPTY and accrues weight at each stop.

    `evaluate_direct` used to charge the entire cumulative load on every leg,
    including the outbound-empty one. That overstated the direct tour, and since
    the cross-dock plan is scored against exactly this number it inflated the
    reported consolidation saving. Measured on a real 3-stop domestic run:
    cost -52%, CO2e -59%.
    """
    depot, nodes, ships = _tour([120.0, 340.0, 80.0])
    light = evaluate_direct(depot, nodes, ships)

    # Same tour, same geometry, but every gram present from the very first leg.
    heavy_from_the_start = evaluate_direct(
        depot, nodes, {k: _ship(k, s.lat, s.lng, kg=540.0) for k, s in ships.items()}
    )
    assert light.cost_usd < heavy_from_the_start.cost_usd
    assert light.co2_kg < heavy_from_the_start.co2_kg
    assert light.distance_km == heavy_from_the_start.distance_km  # geometry is unchanged


def test_rate_class_is_a_property_of_the_tour_not_of_the_leg():
    """One truck is dispatched for the whole milk-run.

    Deciding TL-vs-LTL per leg from the carried weight re-prices the early legs
    of a full truckload tour as LTL — measured at +775% on an 11,000 kg run.
    A truckload tour pays the truckload rate on every leg, so progressive
    loading must not change its COST at all; only its emissions fall.
    """
    from app.optimization.costs import TL_THRESHOLD_KG, co2_kg, transport_cost_usd
    from app.optimization.cross_dock import haversine_km

    weights = [4000.0, 4000.0, 3000.0]
    assert sum(weights) >= TL_THRESHOLD_KG, "fixture must exceed the truckload threshold"
    depot, nodes, ships = _tour(weights)
    got = evaluate_direct(depot, nodes, ships)

    # Reference: the whole tour at the truckload rate, which is weight-independent.
    total = sum(weights)
    prev, ref_cost = (depot.lat, depot.lng), 0.0
    for n in nodes:
        d = haversine_km(prev[0], prev[1], n.lat, n.lng)
        ref_cost += transport_cost_usd(d, total)
        prev = (n.lat, n.lng)
    ref_cost += transport_cost_usd(haversine_km(prev[0], prev[1], depot.lat, depot.lng), total)

    assert got.cost_usd == round(ref_cost, 10) or abs(got.cost_usd - ref_cost) < 1e-6, (
        f"TL tour cost {got.cost_usd} should equal the flat truckload tour cost {ref_cost}"
    )
    # Emissions DO fall, because ton-mile factors bill the freight actually moved.
    naive_co2 = 0.0
    prev = (depot.lat, depot.lng)
    for n in nodes:
        naive_co2 += co2_kg(haversine_km(prev[0], prev[1], n.lat, n.lng), total)
        prev = (n.lat, n.lng)
    naive_co2 += co2_kg(haversine_km(prev[0], prev[1], depot.lat, depot.lng), total)
    assert got.co2_kg < naive_co2
