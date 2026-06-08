"""
Orchestrator — runs all 4 strategies end-to-end.

Pipeline per strategy:
  1. Outlier filter + Stage 1 CP-SAT sourcing — each strategy runs its own
     solve with strategy-specific us_only_sourcing flag:
       cheapest  → global (all 92 distributors, picks cheapest worldwide)
       fastest   → domestic-only (US distributors, 1-day handling advantage)
       greenest  → global (shorter routes = less CO2 naturally emerges)
       balanced  → global
     Strategies with identical us_only flags share a single cached solve to
     avoid redundant MILP calls.
  2. Stage 2 pickup TSP over each strategy's selected distributors.
  3. Cross-dock evaluation per strategy (fastest penalizes hub dwell time,
     greenest rewards consolidation savings).
  4. Compose final RouteAlternative with strategy_math + cost_breakdown.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.optimization import schemas
from app.optimization.costs import (
    AVG_COMPONENT_KG,
    co2_kg,
    haversine_km,
    holding_cost_usd,
    ml_lead_time_days,
    transport_cost_usd,
)
from app.optimization.cross_dock import (
    CrossDockDecision,
    DistributorShipment,
    RouteMetrics,
    evaluate_cross_dock,
    evaluate_direct,
)
from app.optimization.freight_hubs import FREIGHT_HUBS
from app.optimization.routing import GeoPoint, RoutingNode, solve_pickup_tsp
from app.optimization.sourcing import (
    BomLine,
    Offer,
    SourcingResult,
    solve_sourcing,
)
from app.optimization.strategies import (
    STRATEGIES,
    StrategyWeights,
    normalize_objectives,
    weighted_objective,
)

logger = logging.getLogger(__name__)


# ── Input data containers ────────────────────────────────────────────────────

@dataclass
class DistributorMeta:
    id: int
    name: str
    lat: float
    lng: float
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    is_domestic: bool
    tier: str  # 'major'|'mid'|'broker'


# ── Monte Carlo ETA (retained from old optimize.py) ──────────────────────────

def _monte_carlo_eta(base_days: float, n: int = 1000) -> Dict[str, float]:
    samples = []
    for _ in range(n):
        delay = random.gauss(1.0, 0.15)
        disruption = random.choices([0, 1, 3, 7], weights=[0.85, 0.08, 0.05, 0.02])[0]
        samples.append(max(1.0, base_days * delay + disruption))
    samples.sort()
    return {
        "p10": round(samples[int(0.1 * n)], 1),
        "p50": round(samples[int(0.5 * n)], 1),
        "p90": round(samples[int(0.9 * n)], 1),
        "samples": samples[:200],
    }


# ── Main orchestrator ────────────────────────────────────────────────────────

def _build_route_data(
    sourcing: SourcingResult,
    distributors: Dict[int, DistributorMeta],
    depot: GeoPoint,
) -> tuple:
    """Build weight/cost maps, TSP-ordered nodes, shipment list, and direct metrics."""
    weight_by_did: Dict[int, float] = {}
    cost_by_did: Dict[int, float] = {}
    components_by_did: Dict[int, List[str]] = {}
    for a in sourcing.assignments:
        weight_by_did[a.distributor_id] = (
            weight_by_did.get(a.distributor_id, 0.0) + a.quantity * AVG_COMPONENT_KG
        )
        cost_by_did[a.distributor_id] = (
            cost_by_did.get(a.distributor_id, 0.0) + a.line_total
        )
        components_by_did.setdefault(a.distributor_id, []).append(
            f"{a.mpn} × {a.quantity}"
        )

    nodes: List[RoutingNode] = []
    for did in sourcing.selected_distributor_ids:
        d = distributors[did]
        nodes.append(RoutingNode(id=did, lat=d.lat, lng=d.lng, name=d.name))
    tsp_order = solve_pickup_tsp(depot, nodes)
    ordered_nodes = [next(n for n in nodes if n.id == did) for did in tsp_order]

    shipments_by_did: Dict[int, DistributorShipment] = {}
    for did in sourcing.selected_distributor_ids:
        d = distributors[did]
        shipments_by_did[did] = DistributorShipment(
            distributor_id=did, distributor_name=d.name,
            lat=d.lat, lng=d.lng,
            weight_kg=max(weight_by_did[did], 0.1),
            distributor_tier=d.tier,
        )
    shipments_list = list(shipments_by_did.values())
    direct_metrics = evaluate_direct(depot, ordered_nodes, shipments_by_did)

    return (weight_by_did, cost_by_did, components_by_did,
            ordered_nodes, shipments_by_did, shipments_list, direct_metrics)


def optimize_bom(
    bom: List[BomLine],
    offers: List[Offer],
    distributors: Dict[int, DistributorMeta],
    depot: GeoPoint,
    us_only: bool = False,
    graph_aware: bool = False,
) -> schemas.MultiRouteResponse:
    """Run all 4 strategies and return a MultiRouteResponse."""
    if not bom:
        raise ValueError("BOM is empty")

    # ── Stage 1: per-strategy sourcing solve, cached by us_only flag.
    # Strategies with different us_only_sourcing get different supplier pools,
    # which is the primary driver of divergence (cheapest picks global, fastest
    # picks domestic for lower handling times).
    sourcing_cache: Dict[bool, SourcingResult] = {}
    all_outlier_drops = []

    def _get_sourcing(strat) -> SourcingResult:
        # Cache key includes transport_penalty_scale so strategies with different
        # penalty profiles run separate MILP solves.
        cache_key = (
            strat.us_only_sourcing or us_only,
            getattr(strat, "transport_penalty_scale", 1.0),
        )
        if cache_key not in sourcing_cache:
            result = solve_sourcing(bom, offers, strat, us_only=cache_key[0], graph_aware=graph_aware)
            sourcing_cache[cache_key] = result
            all_outlier_drops.extend(result.outlier_drops)
        return sourcing_cache[cache_key]

    # Pre-solve all unique strategy variants upfront
    for strat in STRATEGIES:
        _get_sourcing(strat)

    # ── Run each strategy: build route data + cross-dock decision
    strategy_raw: List[Dict] = []
    for strat in STRATEGIES:
        sourcing = _get_sourcing(strat)
        (weight_by_did, cost_by_did, components_by_did,
         ordered_nodes, shipments_by_did, shipments_list,
         direct_metrics) = _build_route_data(sourcing, distributors, depot)

        decision = evaluate_cross_dock(
            direct_metrics, shipments_list, depot, strat, hubs=FREIGHT_HUBS,
        )
        if decision.enabled and decision.consolidated_metrics:
            m = decision.consolidated_metrics
        else:
            m = direct_metrics
        strategy_raw.append({
            "strategy": strat,
            "sourcing": sourcing,
            "cost": m.cost_usd,
            "time": m.lead_time_days,
            "carbon": m.co2_kg,
            "metrics": m,
            "decision": decision,
            "weight_by_did": weight_by_did,
            "cost_by_did": cost_by_did,
            "components_by_did": components_by_did,
            "ordered_nodes": ordered_nodes,
            "shipments_by_did": shipments_by_did,
        })

    # Normalize across strategies
    normed = normalize_objectives([
        {"cost": r["cost"], "time": r["time"], "carbon": r["carbon"]}
        for r in strategy_raw
    ])

    # ── Assemble RouteAlternative list
    alternatives: List[schemas.RouteAlternative] = []
    for i, r in enumerate(strategy_raw):
        strat: StrategyWeights = r["strategy"]
        m: RouteMetrics = r["metrics"]
        decision: CrossDockDecision = r["decision"]
        norm = normed[i]
        sourcing: SourcingResult = r["sourcing"]
        weight_by_did = r["weight_by_did"]
        cost_by_did = r["cost_by_did"]
        components_by_did = r["components_by_did"]
        ordered_nodes = r["ordered_nodes"]

        # Build route stops.  Leg costs use the full cumulative BOM weight —
        # the same model as evaluate_direct (one truck doing a pickup tour,
        # weight constant throughout).  A return-to-depot stop is appended so
        # that sum(leg_cost_usd) == total_transport_cost_usd exactly.
        stops: List[schemas.RouteStop] = []
        cumulative_weight = max(sum(weight_by_did.values()), 0.1)
        intl_count = 0
        prev_lat, prev_lng = depot.lat, depot.lng
        for seq, node in enumerate(ordered_nodes):
            d = distributors[node.id]
            dist_km = haversine_km(prev_lat, prev_lng, node.lat, node.lng)
            leg_cost = transport_cost_usd(dist_km, cumulative_weight)
            leg_co2 = co2_kg(dist_km, cumulative_weight)
            if not d.is_domestic:
                intl_count += 1
            stops.append(schemas.RouteStop(
                order=seq + 1,
                distributor_id=node.id,
                distributor_name=d.name,
                city=d.city, state=d.state, country=d.country,
                lat=d.lat, lng=d.lng,
                components=components_by_did.get(node.id, []),
                distance_km=round(dist_km, 1),
                leg_cost_usd=round(leg_cost, 2),
                leg_co2e_kg=round(leg_co2, 3),
            ))
            prev_lat, prev_lng = node.lat, node.lng

        # Return-to-depot leg makes sum(leg_cost_usd) == total_transport_cost_usd
        if ordered_nodes:
            last_node = ordered_nodes[-1]
            ret_km = haversine_km(last_node.lat, last_node.lng, depot.lat, depot.lng)
            ret_cost = transport_cost_usd(ret_km, cumulative_weight)
            ret_co2 = co2_kg(ret_km, cumulative_weight)
            stops.append(schemas.RouteStop(
                order=len(ordered_nodes) + 1,
                distributor_id=0,
                distributor_name="Factory (Depot)",
                city=None, state=None, country="USA",
                lat=depot.lat, lng=depot.lng,
                components=[],
                distance_km=round(ret_km, 1),
                leg_cost_usd=round(ret_cost, 2),
                leg_co2e_kg=round(ret_co2, 3),
            ))

        # Totals.  transport_cost is derived from the displayed route stops so
        # that sum(leg_cost_usd) == total_transport_cost_usd exactly.  ETA and
        # CO2 come from the strategy metrics m (which includes cross-dock gains
        # when the hub route is faster/greener than the direct tour).
        component_cost = sum(cost_by_did.values())
        transport_cost = round(sum(s.leg_cost_usd for s in stops), 2)
        holding = holding_cost_usd(component_cost, m.lead_time_days)
        total_cost = component_cost + transport_cost + holding

        # Use ML lead time if available, fall back to route metrics
        # Pick the representative distributor for ML prediction:
        #   median distance, dominant category from BOM, median risk score
        if ordered_nodes:
            rep_node = ordered_nodes[len(ordered_nodes) // 2]
            rep_dist = distributors[rep_node.id]
            rep_d_km = haversine_km(depot.lat, depot.lng, rep_dist.lat, rep_dist.lng)
            rep_tier = rep_dist.tier
        else:
            rep_d_km = 0.0
            rep_tier = "mid"

        ml_eta = ml_lead_time_days(
            distance_km=rep_d_km,
            distributor_tier=rep_tier,
            component_category="Microcontrollers",  # dominant category default
            is_domestic=sourcing.assignments[0].distributor_id in {
                did for did, d in distributors.items() if d.is_domestic
            } if sourcing.assignments else True,
            risk_score=0.5,
            stock_coverage=10.0,
            is_chinese_origin=strat.us_only_sourcing is False and intl_count > 0,
        )
        # Use ML ETA if within reasonable bounds vs route-derived (2x cap prevents
        # sklearn version-mismatch artifacts from inflating predictions 10x).
        route_eta = m.lead_time_days
        if abs(ml_eta - route_eta) / max(route_eta, 1) > 0.10 and ml_eta < route_eta * 2:
            effective_eta = ml_eta
        else:
            effective_eta = route_eta

        # ── Port congestion delay from live feeds (per D-02) ──────────────────
        try:
            from app.optimization.costs import _port_delay_days
            from app.feeds import get_live_data_cache as _get_ldc
            _feed_cache = _get_ldc()
            if _feed_cache is not None and ordered_nodes:
                rep_dist_obj = distributors[rep_node.id]
                port_delay = _port_delay_days(
                    rep_dist_obj.lat, rep_dist_obj.lng, _feed_cache
                )
                effective_eta += port_delay
        except Exception:
            pass  # graceful degradation — no port delay on error

        mc = _monte_carlo_eta(max(effective_eta, 1.0))

        cost_breakdown = schemas.CostBreakdown(
            component_cost=round(component_cost, 2),
            transport_cost=round(transport_cost, 2),
            holding_cost=round(holding, 2),
            total=round(total_cost, 2),
        )

        strategy_math = schemas.StrategyMath(
            weights={"cost": strat.w_cost, "time": strat.w_time, "carbon": strat.w_carbon},
            raw_objective_values={
                "cost": round(m.cost_usd, 2),
                "time": round(m.lead_time_days, 2),
                "carbon": round(m.co2_kg, 3),
            },
            normalized_objective_values={
                "cost": round(norm["cost_n"], 4),
                "time": round(norm["time_n"], 4),
                "carbon": round(norm["carbon_n"], 4),
            },
            weighted_total=round(weighted_objective(norm, strat), 4),
            citations=[
                "ATRI 2023 — Operational Costs of Trucking",
                "EPA SmartWay 2023 — Heavy-Duty Truck Emissions",
                "Gartner 2022 — IT Supply Chain Benchmarks",
                "BTS CFS 2022 — Commodity Flow Survey",
                "Ghodsypour & O'Brien 1998 — Int'l J. Production Economics",
            ],
        )

        cd_info: Optional[schemas.CrossDockInfo]
        if decision.hub is not None:
            cd_info = schemas.CrossDockInfo(
                enabled=decision.enabled,
                hub_id=decision.hub.id,
                hub_name=decision.hub.name,
                hub_city=decision.hub.city,
                hub_state=decision.hub.state,
                hub_lat=decision.hub.latitude,
                hub_lng=decision.hub.longitude,
                savings_vs_direct_pct=decision.savings_vs_direct_pct,
                direct_cost_usd=round(decision.direct_metrics.cost_usd, 2),
                consolidated_cost_usd=round(
                    decision.consolidated_metrics.cost_usd if decision.consolidated_metrics else 0.0, 2
                ),
                rationale=decision.rationale,
            )
        else:
            cd_info = schemas.CrossDockInfo(
                enabled=False,
                direct_cost_usd=round(decision.direct_metrics.cost_usd, 2),
                rationale=decision.rationale,
            )

        sourcing_out = [
            schemas.SourcingAssignment(
                component_id=a.component_id, mpn=a.mpn,
                distributor_id=a.distributor_id,
                distributor_name=a.distributor_name,
                quantity=a.quantity,
                unit_price_usd=a.unit_price_usd,
                line_total_usd=round(a.line_total, 2),
            )
            for a in sourcing.assignments
        ]

        alternatives.append(schemas.RouteAlternative(
            id=strat.id,
            label=strat.label,
            description=strat.description,
            route=stops,
            sourcing=sourcing_out,
            total_cost_usd=round(total_cost, 2),
            total_transport_cost_usd=round(transport_cost, 2),
            total_component_cost_usd=round(component_cost, 2),
            total_co2e_kg=round(m.co2_kg, 3),
            total_distance_km=round(sum(s.distance_km for s in stops), 1),
            base_eta_days=round(m.lead_time_days, 1),
            eta_p10=mc["p10"], eta_p50=mc["p50"], eta_p90=mc["p90"],
            monte_carlo_samples=mc["samples"],
            stop_count=len(stops),
            international_stops=intl_count,
            cost_breakdown=cost_breakdown,
            strategy_math=strategy_math,
            cross_dock=cd_info,
        ))

    # Compute ranks
    def _rank(key_fn):
        vals = [(i, key_fn(a)) for i, a in enumerate(alternatives)]
        vals.sort(key=lambda t: t[1])
        ranks = [0] * len(alternatives)
        for rank, (i, _) in enumerate(vals):
            ranks[i] = rank + 1
        return ranks

    cost_ranks = _rank(lambda a: a.total_cost_usd)
    speed_ranks = _rank(lambda a: a.eta_p50)
    carbon_ranks = _rank(lambda a: a.total_co2e_kg)
    dist_ranks = _rank(lambda a: a.total_distance_km)

    for i, a in enumerate(alternatives):
        a.cost_rank = cost_ranks[i]
        a.speed_rank = speed_ranks[i]
        a.carbon_rank = carbon_ranks[i]
        a.distance_rank = dist_ranks[i]

    # Deduplicate outlier drops across sourcing runs (same drop may appear in
    # both the global and domestic solve)
    seen_drops = set()
    outlier_drops_out = []
    for d in all_outlier_drops:
        key = (d.component_id, d.dropped_distributor_id)
        if key not in seen_drops:
            seen_drops.add(key)
            outlier_drops_out.append(schemas.OutlierDropLog(
                component_id=d.component_id, mpn=d.mpn,
                dropped_distributor_id=d.dropped_distributor_id,
                dropped_price_usd=d.dropped_price_usd,
                median_price_usd=d.median_price_usd,
                reason=d.reason,
            ))

    return schemas.MultiRouteResponse(
        alternatives=alternatives,
        recommended_id="balanced",
        outlier_drops=outlier_drops_out,
    )
