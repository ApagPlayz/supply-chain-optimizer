"""Unit tests for the TSP routing solver."""
from app.optimization.routing import (
    GeoPoint, RoutingNode, solve_pickup_tsp, route_total_distance_km,
)


def test_tsp_single_distributor_returns_single_id():
    depot = GeoPoint(lat=34.0, lng=-82.0)
    nodes = [RoutingNode(id=7, lat=35.0, lng=-83.0, name="d7")]
    order = solve_pickup_tsp(depot, nodes)
    assert order == [7]


def test_tsp_orders_distributors_greedy_on_east_coast():
    # Depot Greenville SC; three distributors roughly collinear north
    depot = GeoPoint(lat=34.8526, lng=-82.3940)
    nodes = [
        RoutingNode(id=10, lat=38.0, lng=-82.0, name="far"),
        RoutingNode(id=20, lat=35.5, lng=-82.0, name="near"),
        RoutingNode(id=30, lat=36.5, lng=-82.0, name="mid"),
    ]
    order = solve_pickup_tsp(depot, nodes)
    # Should visit in geographic order near → mid → far (or reverse)
    assert set(order) == {10, 20, 30}
    assert len(order) == 3
    # Nearest should be first
    assert order[0] == 20


def test_tsp_empty_returns_empty():
    assert solve_pickup_tsp(GeoPoint(0, 0), []) == []


def test_total_distance_closed_tour():
    depot = GeoPoint(0.0, 0.0)
    nodes = [
        RoutingNode(id=1, lat=0.0, lng=1.0, name="a"),
        RoutingNode(id=2, lat=0.0, lng=2.0, name="b"),
    ]
    # Tour: (0,0) → (0,1) → (0,2) → (0,0)
    # Each degree ≈ 111 km at equator; total ≈ 4*111 = 444 km
    d = route_total_distance_km(depot, nodes)
    assert 400 < d < 500
