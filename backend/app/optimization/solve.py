"""
Orchestrator — runs all 4 strategies end-to-end.

Pipeline per strategy:
  1. Outlier filter + Stage 1 CP-SAT sourcing (strategy-agnostic: all use
     min-cost because time/carbon are distance-dependent). Cost-weighted
     strategies reuse the same sourcing result; only the cross-dock
     decision + final ranking differ across strategies.
  2. Stage 2 pickup TSP over selected distributors.
  3. Cross-dock evaluation per strategy (this is where the strategies
     genuinely diverge — fastest avoids hubs, greenest prefers them).
  4. Compose final RouteAlternative with strategy_math + cost_breakdown.

Note: A fully-general formulation would re-run Stage 1 per strategy with
weighted sourcing objectives. For Stage A we deliberately decouple:
Stage 1 picks cheapest suppliers, then Stage 2 + cross-dock evaluate the
weighted objective. Stage B will merge these into a single MILP.
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

def optimize_bom(
    bom: List[BomLine],
    offers: List[Offer],
    distributors: Dict[int, DistributorMeta],
    depot: GeoPoint,
    us_only: bool = True,
) -> schemas.MultiRouteResponse:
    """Run all 4 strategies and return a MultiRouteResponse."""
    if not bom:
        raise ValueError("BOM is empty")

    # ── Stage 1: one cost-minimizing sourcing solve, reused across strategies
    sourcing: SourcingResult = solve_sourcing(
        bom, offers, STRATEGIES[0], us_only=us_only,
    )
    outlier_drops = sourcing.outlier_drops

    # Build per-distributor shipments + weight rollup
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

    # ── Stage 2: TSP over selected distributors
    nodes: List[RoutingNode] = []
    for did in sourcing.selected_distributor_ids:
        d = distributors[did]
        nodes.append(RoutingNode(id=did, lat=d.lat, lng=d.lng, name=d.name))
    tsp_order = solve_pickup_tsp(depot, nodes)
    ordered_nodes = [next(n for n in nodes if n.id == did) for did in tsp_order]

    # Shipment records for cross-dock analysis
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

    direct_metrics: RouteMetrics = evaluate_direct(depot, ordered_nodes, shipments_by_did)

    # ── Run each strategy: cross-dock decision + final metrics
    strategy_raw: List[Dict] = []
    strategy_decisions: Dict[str, CrossDockDecision] = {}
    for strat in STRATEGIES:
        decision = evaluate_cross_dock(
            direct_metrics, shipments_list, depot, strat, hubs=FREIGHT_HUBS,
        )
        strategy_decisions[strat.id] = decision
        if decision.enabled and decision.consolidated_metrics:
            m = decision.consolidated_metrics
        else:
            m = direct_metrics
        strategy_raw.append({
            "strategy": strat,
            "cost": m.cost_usd,
            "time": m.lead_time_days,
            "carbon": m.co2_kg,
            "metrics": m,
            "decision": decision,
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

        # Components list per stop
        stops: List[schemas.RouteStop] = []
        prev_lat, prev_lng = depot.lat, depot.lng
        total_weight = sum(weight_by_did.values())
        for seq, node in enumerate(ordered_nodes):
            d = distributors[node.id]
            dist_km = haversine_km(prev_lat, prev_lng, node.lat, node.lng)
            leg_cost = transport_cost_usd(dist_km, max(total_weight, 0.1))
            leg_co2 = co2_kg(dist_km, max(total_weight, 0.1))
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

        # Totals
        component_cost = sum(cost_by_did.values())
        transport_cost = m.cost_usd
        holding = holding_cost_usd(component_cost, m.lead_time_days)
        total_cost = component_cost + transport_cost + holding

        # Monte Carlo ETA around the final lead time
        mc = _monte_carlo_eta(max(m.lead_time_days, 1.0))

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
            international_stops=0,  # us_only=True by default
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

    outlier_drops_out = [
        schemas.OutlierDropLog(
            component_id=d.component_id, mpn=d.mpn,
            dropped_distributor_id=d.dropped_distributor_id,
            dropped_price_usd=d.dropped_price_usd,
            median_price_usd=d.median_price_usd,
            reason=d.reason,
        )
        for d in outlier_drops
    ]

    return schemas.MultiRouteResponse(
        alternatives=alternatives,
        recommended_id="balanced",
        outlier_drops=outlier_drops_out,
    )
