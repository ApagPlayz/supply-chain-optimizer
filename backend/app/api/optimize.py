"""
Multi-objective route optimization endpoint.
Uses Google OR-Tools for VRP and Monte Carlo simulation for ETA uncertainty.
Carbon footprint estimated from distance × load × emission factor.
Generates multiple route alternatives with different optimization strategies.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import math
import random

from app.core.database import get_db
from app.models.order import CartItem, Order
from app.models.material import Material
from app.models.supplier import Supplier
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/optimize", tags=["optimization"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

EMISSION_FACTOR_KG_CO2_PER_KM_KG = 0.0001  # truck: ~100g CO2/tonne-km
TRUCK_SPEED_KMH = 80.0
FUEL_COST_PER_KM = 0.35  # USD/km average US truck


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def nearest_neighbor_route(locations: List[Dict], depot: Dict) -> List[int]:
    """Greedy nearest-neighbor heuristic (O(n²)) when OR-Tools unavailable."""
    unvisited = list(range(len(locations)))
    route = []
    current = depot
    while unvisited:
        nearest = min(
            unvisited,
            key=lambda i: haversine_km(
                current["lat"], current["lng"],
                locations[i]["lat"], locations[i]["lng"],
            ),
        )
        route.append(nearest)
        current = locations[nearest]
        unvisited.remove(nearest)
    return route


def weighted_vrp_solve(
    locations: List[Dict],
    depot: Dict,
    supplier_groups: Dict[int, Dict],
    cost_weight: float = 0.4,
    time_weight: float = 0.4,
    carbon_weight: float = 0.2,
) -> List[int]:
    """Attempt OR-Tools VRP with weighted objective; fall back to heuristic."""
    try:
        from ortools.constraint_solver import routing_enums_pb2, pywrapcp

        n = len(locations) + 1  # +1 for depot
        all_nodes = [depot] + locations

        # Build weighted cost matrix incorporating distance, time, and carbon
        dist_matrix_raw = [
            [
                haversine_km(all_nodes[i]["lat"], all_nodes[i]["lng"],
                             all_nodes[j]["lat"], all_nodes[j]["lng"])
                for j in range(n)
            ]
            for i in range(n)
        ]

        # Weighted cost matrix: blend distance-cost, time, and carbon
        cost_matrix = []
        for i in range(n):
            row = []
            for j in range(n):
                d = dist_matrix_raw[i][j]
                transport_cost = d * FUEL_COST_PER_KM
                time_cost = d / TRUCK_SPEED_KMH  # hours
                # Estimate CO2 using avg load
                avg_kg = 500.0
                if j > 0:
                    sid = locations[j - 1].get("sid")
                    if sid and sid in supplier_groups:
                        avg_kg = max(supplier_groups[sid]["total_kg"], 1.0)
                carbon_cost = d * avg_kg * EMISSION_FACTOR_KG_CO2_PER_KM_KG
                weighted = (
                    cost_weight * transport_cost +
                    time_weight * time_cost * 50 +  # scale to similar magnitude
                    carbon_weight * carbon_cost * 100
                )
                row.append(int(weighted * 100))  # integer for OR-Tools
            cost_matrix.append(row)

        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def dist_cb(from_idx, to_idx):
            return cost_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

        transit_cb_idx = routing.RegisterTransitCallback(dist_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = 3

        solution = routing.SolveWithParameters(params)
        if not solution:
            return nearest_neighbor_route(locations, depot)

        route = []
        idx = routing.Start(0)
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx) - 1
            if node >= 0:
                route.append(node)
            idx = solution.Value(routing.NextVar(idx))
        return route

    except ImportError:
        return nearest_neighbor_route(locations, depot)


def monte_carlo_eta(base_days: float, n: int = 1000) -> Dict[str, float]:
    """Simulate delivery time distribution with random disruptions."""
    samples = []
    for _ in range(n):
        delay_factor = random.gauss(1.0, 0.15)
        disruption = random.choices([0, 1, 3, 7], weights=[0.85, 0.08, 0.05, 0.02])[0]
        samples.append(max(1, base_days * delay_factor + disruption))
    samples.sort()
    p10 = samples[int(0.10 * n)]
    p50 = samples[int(0.50 * n)]
    p90 = samples[int(0.90 * n)]
    return {"p10": round(p10, 1), "p50": round(p50, 1), "p90": round(p90, 1), "samples": samples[:200]}


def compute_route_metrics(
    order_indices: List[int],
    locations: List[Dict],
    supplier_groups: Dict[int, Dict],
    depot: Dict,
) -> Dict[str, Any]:
    """Given an ordering of stops, compute full route metrics."""
    route_stops = []
    total_material_cost = sum(v["material_cost"] for v in supplier_groups.values())
    total_transport_cost = 0.0
    total_co2 = 0.0
    total_dist = 0.0
    max_lead = 0
    prev = depot

    for seq, idx in enumerate(order_indices):
        loc = locations[idx]
        sid = loc["sid"]
        grp = supplier_groups[sid]
        sup = grp["supplier"]
        dist = haversine_km(prev["lat"], prev["lng"], loc["lat"], loc["lng"])
        leg_cost = dist * FUEL_COST_PER_KM
        co2 = dist * grp["total_kg"] * EMISSION_FACTOR_KG_CO2_PER_KM_KG
        total_dist += dist
        total_transport_cost += leg_cost
        total_co2 += co2
        max_lead = max(max_lead, sup.lead_time_days)

        route_stops.append({
            "order": seq + 1,
            "supplier_id": sid,
            "supplier_name": sup.name,
            "city": sup.city,
            "state": sup.state,
            "lat": sup.latitude,
            "lng": sup.longitude,
            "material_names": grp["materials"],
            "distance_km": round(dist, 1),
            "leg_cost_usd": round(leg_cost, 2),
            "leg_co2e_kg": round(co2, 3),
        })
        prev = loc

    # Return trip to depot
    return_dist = haversine_km(prev["lat"], prev["lng"], depot["lat"], depot["lng"])
    total_dist += return_dist
    total_cost = total_material_cost + total_transport_cost

    base_eta = max_lead + (total_dist / TRUCK_SPEED_KMH) / 24
    mc = monte_carlo_eta(base_eta)

    return {
        "route": route_stops,
        "total_cost_usd": round(total_cost, 2),
        "total_transport_cost_usd": round(total_transport_cost, 2),
        "total_material_cost_usd": round(total_material_cost, 2),
        "total_co2e_kg": round(total_co2, 3),
        "total_distance_km": round(total_dist, 1),
        "base_eta_days": round(base_eta, 1),
        "eta_p10": mc["p10"],
        "eta_p50": mc["p50"],
        "eta_p90": mc["p90"],
        "monte_carlo_samples": mc["samples"],
        "max_lead_time_days": max_lead,
        "stop_count": len(route_stops),
    }


# ─── Schemas ──────────────────────────────────────────────────────────────────

class RouteStop(BaseModel):
    order: int
    supplier_id: int
    supplier_name: str
    city: Optional[str]
    state: Optional[str]
    lat: float
    lng: float
    material_names: List[str]
    distance_km: float
    leg_cost_usd: float
    leg_co2e_kg: float


class RouteAlternative(BaseModel):
    id: str                       # e.g. "cheapest", "fastest", "greenest", "balanced"
    label: str                    # human-readable label
    description: str              # short explanation of the strategy
    route: List[RouteStop]
    total_cost_usd: float
    total_transport_cost_usd: float
    total_material_cost_usd: float
    total_co2e_kg: float
    total_distance_km: float
    base_eta_days: float
    eta_p10: float
    eta_p50: float
    eta_p90: float
    monte_carlo_samples: List[float]
    max_lead_time_days: int
    stop_count: int
    # Relative rankings (1 = best among alternatives for that metric)
    cost_rank: int = 0
    speed_rank: int = 0
    carbon_rank: int = 0
    distance_rank: int = 0


class MultiRouteResponse(BaseModel):
    alternatives: List[RouteAlternative]
    recommended_id: str  # which alternative we recommend


# ─── Endpoint ─────────────────────────────────────────────────────────────────

STRATEGIES = [
    {
        "id": "cheapest",
        "label": "Lowest Cost",
        "description": "Minimizes total transport + material cost",
        "weights": (0.8, 0.1, 0.1),
    },
    {
        "id": "fastest",
        "label": "Fastest Delivery",
        "description": "Minimizes travel time and distances",
        "weights": (0.1, 0.8, 0.1),
    },
    {
        "id": "greenest",
        "label": "Lowest Carbon",
        "description": "Minimizes CO₂ emissions across all legs",
        "weights": (0.1, 0.1, 0.8),
    },
    {
        "id": "balanced",
        "label": "Balanced",
        "description": "Equal weighting across cost, speed, and carbon",
        "weights": (0.34, 0.33, 0.33),
    },
]


@router.post("/vrp", response_model=MultiRouteResponse)
async def optimize_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate multiple route alternatives with different optimization strategies.

    Returns 4 alternatives (cheapest, fastest, greenest, balanced) each with
    full metrics so the user can compare trade-offs.
    """
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    depot = {"lat": current_user.latitude, "lng": current_user.longitude}

    # Build stop list (group by supplier)
    supplier_groups: Dict[int, Dict] = {}
    for item in cart_items:
        sup = db.query(Supplier).filter(Supplier.id == item.supplier_id).first()
        mat = db.query(Material).filter(Material.id == item.material_id).first()
        if not sup or not mat:
            continue
        if sup.id not in supplier_groups:
            supplier_groups[sup.id] = {
                "supplier": sup, "materials": [], "total_kg": 0.0, "material_cost": 0.0
            }
        supplier_groups[sup.id]["materials"].append(mat.name)
        kg = item.quantity if mat.unit == "kg" else item.quantity * 0.5
        supplier_groups[sup.id]["total_kg"] += kg
        supplier_groups[sup.id]["material_cost"] += (item.unit_price or mat.current_price or 0) * item.quantity

    if not supplier_groups:
        raise HTTPException(status_code=400, detail="No valid cart items with supplier/material data")

    locations = [
        {"lat": v["supplier"].latitude, "lng": v["supplier"].longitude, "sid": sid}
        for sid, v in supplier_groups.items()
    ]

    # Generate alternatives
    alternatives_raw = []
    for strat in STRATEGIES:
        cw, tw, carw = strat["weights"]
        order_indices = weighted_vrp_solve(locations, depot, supplier_groups, cw, tw, carw)
        metrics = compute_route_metrics(order_indices, locations, supplier_groups, depot)
        alternatives_raw.append({
            **strat,
            **metrics,
        })

    # Compute rankings (1 = best)
    def rank_by(key: str, reverse: bool = False):
        vals = [a[key] for a in alternatives_raw]
        sorted_indices = sorted(range(len(vals)), key=lambda i: vals[i], reverse=reverse)
        ranks = [0] * len(vals)
        for rank, i in enumerate(sorted_indices):
            ranks[i] = rank + 1
        return ranks

    cost_ranks = rank_by("total_cost_usd")
    speed_ranks = rank_by("eta_p50")
    carbon_ranks = rank_by("total_co2e_kg")
    distance_ranks = rank_by("total_distance_km")

    alternatives = []
    for i, a in enumerate(alternatives_raw):
        alternatives.append(RouteAlternative(
            id=a["id"],
            label=a["label"],
            description=a["description"],
            route=[RouteStop(**s) for s in a["route"]],
            total_cost_usd=a["total_cost_usd"],
            total_transport_cost_usd=a["total_transport_cost_usd"],
            total_material_cost_usd=a["total_material_cost_usd"],
            total_co2e_kg=a["total_co2e_kg"],
            total_distance_km=a["total_distance_km"],
            base_eta_days=a["base_eta_days"],
            eta_p10=a["eta_p10"],
            eta_p50=a["eta_p50"],
            eta_p90=a["eta_p90"],
            monte_carlo_samples=a["monte_carlo_samples"],
            max_lead_time_days=a["max_lead_time_days"],
            stop_count=a["stop_count"],
            cost_rank=cost_ranks[i],
            speed_rank=speed_ranks[i],
            carbon_rank=carbon_ranks[i],
            distance_rank=distance_ranks[i],
        ))

    # Persist the balanced route as the default order
    balanced = next(a for a in alternatives_raw if a["id"] == "balanced")
    order = Order(
        user_id=current_user.id,
        status="optimized",
        total_cost=balanced["total_cost_usd"],
        total_co2e_kg=balanced["total_co2e_kg"],
        eta_days=balanced["base_eta_days"],
        eta_lower_ci=balanced["eta_p10"],
        eta_upper_ci=balanced["eta_p90"],
        optimized_route=balanced["route"],
        monte_carlo_results={"p10": balanced["eta_p10"], "p50": balanced["eta_p50"], "p90": balanced["eta_p90"]},
        items=[{"material_id": ci.material_id, "supplier_id": ci.supplier_id,
                "quantity": ci.quantity, "unit_price": ci.unit_price} for ci in cart_items],
    )
    db.add(order)
    db.commit()

    # Recommend balanced by default
    return MultiRouteResponse(
        alternatives=alternatives,
        recommended_id="balanced",
    )


class ScenarioRequest(BaseModel):
    tariff_multiplier: float = 1.0
    port_closure_ids: List[int] = []
    supplier_failure_ids: List[int] = []
    demand_spike: float = 1.0


@router.post("/scenario")
async def run_scenario(
    body: ScenarioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Digital twin: re-run optimization under what-if conditions."""
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    adjustments = []
    for item in cart_items:
        sup = db.query(Supplier).filter(Supplier.id == item.supplier_id).first()
        mat = db.query(Material).filter(Material.id == item.material_id).first()
        base_price = (item.unit_price or (mat.current_price if mat else 0) or 0)
        tariff_adj = base_price * body.tariff_multiplier
        supplier_failed = item.supplier_id in body.supplier_failure_ids
        adjustments.append({
            "material": mat.name if mat else "Unknown",
            "supplier": sup.name if sup else "Unknown",
            "base_price": base_price,
            "scenario_price": tariff_adj if not supplier_failed else None,
            "supplier_available": not supplier_failed,
            "quantity": item.quantity,
            "base_cost": base_price * item.quantity,
            "scenario_cost": tariff_adj * item.quantity * body.demand_spike if not supplier_failed else None,
        })

    base_total = sum(a["base_cost"] for a in adjustments)
    scenario_total = sum(a["scenario_cost"] for a in adjustments if a["scenario_cost"] is not None)
    cost_delta_pct = round((scenario_total - base_total) / base_total * 100, 1) if base_total else 0

    failed_items = [a for a in adjustments if not a["supplier_available"]]
    mc = monte_carlo_eta(14 * (1 + len(failed_items) * 0.5))

    return {
        "scenario": {
            "tariff_multiplier": body.tariff_multiplier,
            "port_closures": len(body.port_closure_ids),
            "supplier_failures": len(body.supplier_failure_ids),
            "demand_spike": body.demand_spike,
        },
        "base_total_cost": round(base_total, 2),
        "scenario_total_cost": round(scenario_total, 2),
        "cost_delta_pct": cost_delta_pct,
        "disrupted_items": len(failed_items),
        "eta_p50": mc["p50"],
        "eta_p90": mc["p90"],
        "item_breakdown": adjustments,
    }
