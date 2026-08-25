"""
Stage 2 — Pickup TSP over the distributors selected by Stage 1.

WHAT THIS IS, EXACTLY: a single-vehicle, uncapacitated, SYMMETRIC
Travelling Salesman Problem. One vehicle leaves the depot, visits every
selected distributor exactly once, and returns. There is no capacity
dimension, no time window, no demand dimension and no second vehicle — so
this is a TSP, not a VRP, even though the endpoint that ultimately calls it
is named ``POST /api/v1/optimize/vrp``. That route name is historical and is
kept deliberately so the public API does not break; it is not a claim about
the model.

The matrix is great-circle (haversine) distance rounded to integer metres,
so d(i, j) == d(j, i) by construction. That makes it a SYMMETRIC TSP.
Nothing here is asymmetric — asymmetry would need directional costs
(one-way streets, road distances, traffic), which this model does not have.

SOLVER: OR-Tools routing (``pywrapcp.RoutingModel``), PATH_CHEAPEST_ARC
first-solution strategy, GUIDED_LOCAL_SEARCH metaheuristic, 3-second time
limit by default. GUIDED_LOCAL_SEARCH is a metaheuristic, so the tour it
returns is a good local optimum, not a proven optimum. If the solver returns
no solution at all, ``solve_pickup_tsp`` falls back to a greedy
nearest-neighbour tour so the caller always gets a usable order.

NOT BUILT: OSRM (or any other) road driving distances in the optimizer. The
map page fetches OSRM geometry purely to DRAW a road-shaped polyline; the
optimizer never sees a road distance. Every kilometre, dollar, day and kg of
CO2 in this pipeline is derived from great-circle distance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.optimization.costs import haversine_km


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(frozen=True)
class RoutingNode:
    """A single location in the pickup route (distributor or depot)."""
    id: int  # distributor_id, or -1 for depot
    lat: float
    lng: float
    name: str


def _nearest_neighbor_order(nodes: List[RoutingNode]) -> List[int]:
    """Greedy fallback ordering starting at index 0 (depot)."""
    n = len(nodes)
    visited = {0}
    order = [0]
    current = 0
    while len(visited) < n:
        best = None
        best_d = float("inf")
        for j in range(n):
            if j in visited:
                continue
            d = haversine_km(nodes[current].lat, nodes[current].lng,
                             nodes[j].lat, nodes[j].lng)
            if d < best_d:
                best_d = d
                best = j
        order.append(best)
        visited.add(best)
        current = best
    return order


def solve_pickup_tsp(
    depot: GeoPoint,
    distributor_nodes: List[RoutingNode],
    time_limit_seconds: int = 3,
) -> List[int]:
    """
    Return an ordered list of distributor_ids representing the pickup route.

    One vehicle, no capacity constraint, symmetric haversine costs. The tour
    starts and ends at the depot. The returned list EXCLUDES the depot — only
    the distributor ids in visit order. If distributor_nodes has a single
    element, returns that id directly.

    ``time_limit_seconds`` bounds the GUIDED_LOCAL_SEARCH phase; on the tour
    sizes this project produces (a handful of stops) the search converges long
    before it, but the result is still a local optimum rather than a certified
    one. On solver failure the return value is the greedy nearest-neighbour
    order instead.
    """
    if not distributor_nodes:
        return []
    if len(distributor_nodes) == 1:
        return [distributor_nodes[0].id]

    depot_node = RoutingNode(id=-1, lat=depot.lat, lng=depot.lng, name="depot")
    nodes = [depot_node] + list(distributor_nodes)
    n = len(nodes)

    # Distance matrix in meters (integer for OR-Tools)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            matrix[i][j] = int(round(
                haversine_km(nodes[i].lat, nodes[i].lng,
                             nodes[j].lat, nodes[j].lng) * 1000
            ))

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_cb(from_idx, to_idx):
        return matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    transit_cb_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = time_limit_seconds

    solution = routing.SolveWithParameters(params)
    if not solution:
        # Fall back to greedy order on real nodes (exclude depot index 0)
        greedy = _nearest_neighbor_order(nodes)
        return [nodes[i].id for i in greedy if i != 0]

    order_ids: List[int] = []
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        node_idx = manager.IndexToNode(idx)
        if node_idx != 0:
            order_ids.append(nodes[node_idx].id)
        idx = solution.Value(routing.NextVar(idx))
    return order_ids


def route_total_distance_km(
    depot: GeoPoint,
    ordered_nodes: List[RoutingNode],
) -> float:
    """Haversine distance of the closed tour depot → n1 → n2 → ... → depot."""
    if not ordered_nodes:
        return 0.0
    total = haversine_km(depot.lat, depot.lng,
                         ordered_nodes[0].lat, ordered_nodes[0].lng)
    for i in range(len(ordered_nodes) - 1):
        total += haversine_km(
            ordered_nodes[i].lat, ordered_nodes[i].lng,
            ordered_nodes[i + 1].lat, ordered_nodes[i + 1].lng,
        )
    total += haversine_km(
        ordered_nodes[-1].lat, ordered_nodes[-1].lng,
        depot.lat, depot.lng,
    )
    return total
