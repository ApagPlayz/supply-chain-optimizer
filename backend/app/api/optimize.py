"""
Multi-objective route optimization endpoint.
Uses Google OR-Tools for VRP and Monte Carlo simulation for ETA uncertainty.
Carbon footprint estimated from distance x load x emission factor.
Generates multiple route alternatives with different optimization strategies.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import math
import random

from app.core.database import get_db
from app.core.config import settings
from app.models.order import CartItem, Order
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/optimize", tags=["optimization"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

EMISSION_FACTOR_KG_CO2_PER_KM_KG = 0.0001  # truck: ~100g CO2/tonne-km
TRUCK_SPEED_KMH = 80.0
FUEL_COST_PER_KM = 0.35  # USD/km average US truck
AVG_COMPONENT_KG = 0.05  # avg weight per electronic component unit


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def nearest_neighbor_route(locations: List[Dict], depot: Dict) -> List[int]:
    """Greedy nearest-neighbor heuristic (O(n^2)) when OR-Tools unavailable."""
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
    distributor_groups: Dict[int, Dict],
    cost_weight: float = 0.4,
    time_weight: float = 0.4,
    carbon_weight: float = 0.2,
) -> List[int]:
    """Attempt OR-Tools VRP with weighted objective; fall back to heuristic."""
    try:
        from ortools.constraint_solver import routing_enums_pb2, pywrapcp

        n = len(locations) + 1  # +1 for depot
        all_nodes = [depot] + locations

        dist_matrix_raw = [
            [
                haversine_km(all_nodes[i]["lat"], all_nodes[i]["lng"],
                             all_nodes[j]["lat"], all_nodes[j]["lng"])
                for j in range(n)
            ]
            for i in range(n)
        ]

        cost_matrix = []
        for i in range(n):
            row = []
            for j in range(n):
                d = dist_matrix_raw[i][j]
                transport_cost = d * FUEL_COST_PER_KM
                time_cost = d / TRUCK_SPEED_KMH
                avg_kg = 1.0
                if j > 0:
                    did = locations[j - 1].get("did")
                    if did and did in distributor_groups:
                        avg_kg = max(distributor_groups[did]["total_kg"], 0.1)
                carbon_cost = d * avg_kg * EMISSION_FACTOR_KG_CO2_PER_KM_KG
                weighted = (
                    cost_weight * transport_cost +
                    time_weight * time_cost * 50 +
                    carbon_weight * carbon_cost * 100
                )
                row.append(int(weighted * 100))
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
    distributor_groups: Dict[int, Dict],
    depot: Dict,
) -> Dict[str, Any]:
    """Given an ordering of stops, compute full route metrics."""
    route_stops = []
    total_component_cost = sum(v["component_cost"] for v in distributor_groups.values())
    total_transport_cost = 0.0
    total_co2 = 0.0
    total_dist = 0.0
    prev = depot

    for seq, idx in enumerate(order_indices):
        loc = locations[idx]
        did = loc["did"]
        grp = distributor_groups[did]
        dist_obj = grp["distributor"]
        dist = haversine_km(prev["lat"], prev["lng"], loc["lat"], loc["lng"])
        leg_cost = dist * FUEL_COST_PER_KM
        co2 = dist * grp["total_kg"] * EMISSION_FACTOR_KG_CO2_PER_KM_KG
        total_dist += dist
        total_transport_cost += leg_cost
        total_co2 += co2

        route_stops.append({
            "order": seq + 1,
            "distributor_id": did,
            "distributor_name": dist_obj.name,
            "city": dist_obj.city,
            "state": dist_obj.state,
            "country": dist_obj.country,
            "lat": dist_obj.latitude,
            "lng": dist_obj.longitude,
            "components": grp["components"],
            "distance_km": round(dist, 1),
            "leg_cost_usd": round(leg_cost, 2),
            "leg_co2e_kg": round(co2, 3),
        })
        prev = loc

    return_dist = haversine_km(prev["lat"], prev["lng"], depot["lat"], depot["lng"])
    total_dist += return_dist
    total_cost = total_component_cost + total_transport_cost

    # ETA: use EasyPost SmartRate if configured, otherwise haversine estimate
    intl_stops = sum(1 for g in distributor_groups.values() if not g["distributor"].is_domestic)
    base_eta = (total_dist / TRUCK_SPEED_KMH) / 24 + intl_stops * 5  # 5 extra days per intl stop

    # Try EasyPost SmartRate for real transit time (domestic only)
    if settings.EASYPOST_API_KEY and not intl_stops and route_stops:
        try:
            from app.core.clients.easypost_client import EasyPostClient, _coords_to_zip
            import asyncio
            ep_client = EasyPostClient(settings.EASYPOST_API_KEY)
            # Use first → last stop as representative leg
            first_stop = route_stops[0]
            last_stop = route_stops[-1]
            smartrate = asyncio.get_event_loop().run_until_complete(
                ep_client.get_transit_days_from_coords(
                    from_lat=first_stop["lat"], from_lng=first_stop["lng"],
                    to_lat=depot["lat"], to_lng=depot["lng"],
                )
            )
            if smartrate:
                base_eta = smartrate["p50"]
        except Exception:
            pass  # Fall back to haversine estimate silently

    mc = monte_carlo_eta(max(base_eta, 1))

    return {
        "route": route_stops,
        "total_cost_usd": round(total_cost, 2),
        "total_transport_cost_usd": round(total_transport_cost, 2),
        "total_component_cost_usd": round(total_component_cost, 2),
        "total_co2e_kg": round(total_co2, 3),
        "total_distance_km": round(total_dist, 1),
        "base_eta_days": round(base_eta, 1),
        "eta_p10": mc["p10"],
        "eta_p50": mc["p50"],
        "eta_p90": mc["p90"],
        "monte_carlo_samples": mc["samples"],
        "stop_count": len(route_stops),
        "international_stops": intl_stops,
    }


# ─── Schemas ──────────────────────────────────────────────────────────────────

class RouteStop(BaseModel):
    order: int
    distributor_id: int
    distributor_name: str
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    lat: float
    lng: float
    components: List[str]
    distance_km: float
    leg_cost_usd: float
    leg_co2e_kg: float


class RouteAlternative(BaseModel):
    id: str
    label: str
    description: str
    route: List[RouteStop]
    total_cost_usd: float
    total_transport_cost_usd: float
    total_component_cost_usd: float
    total_co2e_kg: float
    total_distance_km: float
    base_eta_days: float
    eta_p10: float
    eta_p50: float
    eta_p90: float
    monte_carlo_samples: List[float]
    stop_count: int
    international_stops: int
    cost_rank: int = 0
    speed_rank: int = 0
    carbon_rank: int = 0
    distance_rank: int = 0


class MultiRouteResponse(BaseModel):
    alternatives: List[RouteAlternative]
    recommended_id: str


# ─── Endpoint ─────────────────────────────────────────────────────────────────

STRATEGIES = [
    {
        "id": "cheapest",
        "label": "Lowest Cost",
        "description": "Minimizes total transport + component cost",
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
        "description": "Minimizes CO2 emissions across all legs",
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
    """Generate multiple route alternatives across distributor warehouses.

    Groups cart items by distributor, then solves VRP for 4 different
    optimization strategies (cheapest, fastest, greenest, balanced).
    """
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    depot = {"lat": current_user.latitude, "lng": current_user.longitude}

    # Group cart items by distributor
    distributor_groups: Dict[int, Dict] = {}
    for item in cart_items:
        dist = db.query(Distributor).filter(Distributor.id == item.distributor_id).first()
        comp = db.query(Component).filter(Component.id == item.component_id).first()
        if not dist or not comp:
            continue
        if dist.id not in distributor_groups:
            distributor_groups[dist.id] = {
                "distributor": dist, "components": [], "total_kg": 0.0, "component_cost": 0.0
            }
        distributor_groups[dist.id]["components"].append(f"{comp.mpn} ({comp.manufacturer})")
        distributor_groups[dist.id]["total_kg"] += item.quantity * AVG_COMPONENT_KG
        distributor_groups[dist.id]["component_cost"] += (item.unit_price or 0) * item.quantity

    if not distributor_groups:
        raise HTTPException(status_code=400, detail="No valid cart items")

    locations = [
        {"lat": v["distributor"].latitude, "lng": v["distributor"].longitude, "did": did}
        for did, v in distributor_groups.items()
    ]

    # Generate alternatives
    alternatives_raw = []
    for strat in STRATEGIES:
        cw, tw, carw = strat["weights"]
        order_indices = weighted_vrp_solve(locations, depot, distributor_groups, cw, tw, carw)
        metrics = compute_route_metrics(order_indices, locations, distributor_groups, depot)
        alternatives_raw.append({**strat, **metrics})

    # Compute rankings
    def rank_by(key: str):
        vals = [a[key] for a in alternatives_raw]
        sorted_indices = sorted(range(len(vals)), key=lambda i: vals[i])
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
            id=a["id"], label=a["label"], description=a["description"],
            route=[RouteStop(**s) for s in a["route"]],
            total_cost_usd=a["total_cost_usd"],
            total_transport_cost_usd=a["total_transport_cost_usd"],
            total_component_cost_usd=a["total_component_cost_usd"],
            total_co2e_kg=a["total_co2e_kg"],
            total_distance_km=a["total_distance_km"],
            base_eta_days=a["base_eta_days"],
            eta_p10=a["eta_p10"], eta_p50=a["eta_p50"], eta_p90=a["eta_p90"],
            monte_carlo_samples=a["monte_carlo_samples"],
            stop_count=a["stop_count"],
            international_stops=a["international_stops"],
            cost_rank=cost_ranks[i], speed_rank=speed_ranks[i],
            carbon_rank=carbon_ranks[i], distance_rank=distance_ranks[i],
        ))

    # Persist balanced route as default order
    balanced = next(a for a in alternatives_raw if a["id"] == "balanced")
    order = Order(
        user_id=current_user.id, status="optimized",
        total_cost=balanced["total_cost_usd"],
        total_co2e_kg=balanced["total_co2e_kg"],
        eta_days=balanced["base_eta_days"],
        eta_lower_ci=balanced["eta_p10"], eta_upper_ci=balanced["eta_p90"],
        optimized_route=balanced["route"],
        monte_carlo_results={"p10": balanced["eta_p10"], "p50": balanced["eta_p50"], "p90": balanced["eta_p90"]},
        items=[{"component_id": ci.component_id, "distributor_id": ci.distributor_id,
                "quantity": ci.quantity, "unit_price": ci.unit_price} for ci in cart_items],
    )
    db.add(order)
    db.commit()

    return MultiRouteResponse(alternatives=alternatives, recommended_id="balanced")


class ScenarioRequest(BaseModel):
    tariff_multiplier: float = 1.0
    distributor_failure_ids: List[int] = []
    demand_spike: float = 1.0


@router.post("/scenario")
async def run_scenario(
    body: ScenarioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Digital twin: re-run optimization under what-if conditions.

    If body.tariff_multiplier == 1.0 (default/unchanged) AND SupplyMaven is configured,
    auto-populate tariff_multiplier from live trade policy data.
    """
    # Auto-populate tariff multiplier from live data if not overridden
    if body.tariff_multiplier == 1.0 and settings.SUPPLYMAVEN_API_KEY:
        try:
            from app.core.clients.supplymaven_client import SupplyMavenClient
            sm_client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
            trade_data = await sm_client.get_trade_policy_impacts()
            live_mult = sm_client.tariffs_to_scenario_multiplier(trade_data)
            if live_mult != 1.0:
                body = ScenarioRequest(
                    tariff_multiplier=live_mult,
                    distributor_failure_ids=body.distributor_failure_ids,
                    demand_spike=body.demand_spike,
                )
        except Exception:
            pass  # Silently fall back to manual value

    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    adjustments = []
    for item in cart_items:
        dist = db.query(Distributor).filter(Distributor.id == item.distributor_id).first()
        comp = db.query(Component).filter(Component.id == item.component_id).first()
        base_price = item.unit_price or 0
        tariff_adj = base_price * body.tariff_multiplier
        dist_failed = item.distributor_id in body.distributor_failure_ids
        adjustments.append({
            "component": comp.mpn if comp else "Unknown",
            "distributor": dist.name if dist else "Unknown",
            "base_price": base_price,
            "scenario_price": tariff_adj if not dist_failed else None,
            "distributor_available": not dist_failed,
            "quantity": item.quantity,
            "base_cost": base_price * item.quantity,
            "scenario_cost": tariff_adj * item.quantity * body.demand_spike if not dist_failed else None,
        })

    base_total = sum(a["base_cost"] for a in adjustments)
    scenario_total = sum(a["scenario_cost"] for a in adjustments if a["scenario_cost"] is not None)
    cost_delta_pct = round((scenario_total - base_total) / base_total * 100, 1) if base_total else 0

    failed_items = [a for a in adjustments if not a["distributor_available"]]
    mc = monte_carlo_eta(14 * (1 + len(failed_items) * 0.5))

    return {
        "scenario": {
            "tariff_multiplier": body.tariff_multiplier,
            "distributor_failures": len(body.distributor_failure_ids),
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
