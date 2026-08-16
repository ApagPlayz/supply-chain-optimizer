"""
Orchestrator — runs all 4 strategies end-to-end.

Pipeline per strategy:
  1. Outlier filter + Stage 1 CP-SAT sourcing — each strategy runs its own
     MILP solve with strategy-specific parameters:
       cheapest  → global (us_only=False, penalty_scale=1.0, consolidation=0.5)
       fastest   → domestic (us_only=True, penalty_scale=0.0, consolidation=3.0)
       greenest  → domestic (us_only=True, penalty_scale=2.5, consolidation=2.5)
       balanced  → domestic (us_only=True, penalty_scale=1.5, consolidation=2.0)
     Strategies share a cached solve only when ALL of (us_only, penalty_scale,
     consolidation_bonus) are identical — in practice each strategy is distinct.
  2. Stage 2 pickup TSP over each strategy's selected distributors.
     International distributors are air-freight legs (not truck tour stops).
  3. Cross-dock evaluation per strategy (fastest penalizes hub dwell time,
     greenest rewards consolidation savings).
  4. Compose final RouteAlternative with strategy_math + cost_breakdown.
     CO2 total is derived from the displayed route stops so it is always
     consistent with the route visualisation, regardless of cross-dock state.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.optimization import schemas
from app.optimization.constants import AIR_FREIGHT_BASE_USD, AIR_FREIGHT_RATE_USD_PER_KG
from app.optimization.costs import (
    AVG_COMPONENT_KG,
    co2_kg,
    haversine_km,
    holding_cost_usd,
    ml_factory_lead_time_days,
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

def _assess_supply_risk(
    sourcing: SourcingResult,
    bom: List[BomLine],
    offers: List[Offer],
    route_eta_days: float,
) -> schemas.SupplyRiskInfo:
    """Score every assigned BOM line with the ML factory-lead-time model.

    Unlike the gate this replaced, there is no threshold to clear: the model is
    consulted for EVERY line whose category is inside its trained vocabulary,
    on every strategy, on every run. A line is "declined" — not silently
    zero-filled — when its category was never observed in the panel.

    ``risk_adjusted_eta_days`` adds the longest factory lead time among
    ZERO-BUFFER lines (lines where the plan takes 100% of the distributor's
    reported shelf, so a stale inventory snapshot puts the balance on factory
    lead time) to the route ETA. When every line ships with buffer to spare it
    equals the route ETA, which is the correct answer, not a suppressed one.
    """
    line_by_cid = {b.component_id: b for b in bom}
    offer_by_key = {(o.component_id, o.distributor_id): o for o in offers}

    scored = 0
    declined = 0
    declined_reason: Optional[str] = None
    model_name: Optional[str] = None
    model_source_name: Optional[str] = None
    unavailable_reason: Optional[str] = None
    max_days: Optional[float] = None
    driver_mpn: Optional[str] = None
    zero_buffer_lines = 0
    zero_buffer_max_days = 0.0

    for a in sourcing.assignments:
        offer = offer_by_key.get((a.component_id, a.distributor_id))
        line = line_by_cid.get(a.component_id)
        if offer is None or line is None:
            continue
        if not (line.dk_category or line.category):
            declined += 1
            declined_reason = declined_reason or "BOM line carries no component category"
            continue

        # Pass everything we have; the resolved feature schema decides what it
        # consumes, so this call site does not change as the feature set grows.
        result = ml_factory_lead_time_days({
            "dk_category": line.dk_category,
            "dk_subcategory": line.dk_subcategory,
            "category": line.category,
            "manufacturer": line.manufacturer,
            "lifecycle_status": line.lifecycle_status,
            "is_normally_stocked": line.is_normally_stocked,
            "parameter_count": line.parameter_count,
            "package_case": line.package_case,
            "htsus_code": line.htsus_code,
            "rohs_status": line.rohs_status,
            "max_break_qty": line.max_break_qty,
            "price_break_count": line.price_break_count,
            # DigiKey's own price for the part — the SAME column the model trained
            # on. Falls back to this offer's price only when DigiKey never quoted
            # one, and the schema declines the line rather than guessing if both
            # are absent.
            "unit_price": (
                line.digikey_unit_price
                if line.digikey_unit_price is not None else float(offer.price_usd)
            ),
            "moq": offer.moq,
            "packaging": offer.packaging,
            "standard_pack": offer.standard_pack,
        })
        if not result.available or result.days is None:
            declined += 1
            declined_reason = declined_reason or result.reason
            unavailable_reason = unavailable_reason or result.reason
            continue

        scored += 1
        model_name = model_name or result.model_name
        model_source_name = model_source_name or result.model_source
        if max_days is None or result.days > max_days:
            max_days = result.days
            driver_mpn = a.mpn

        # Zero buffer: the plan takes the distributor's entire reported shelf for
        # this line (the MILP fills an offer to the brim when it cannot cover the
        # whole line). Nothing is left over if the weekly snapshot was stale.
        if offer.stock > 0 and a.quantity >= offer.stock:
            zero_buffer_lines += 1
            zero_buffer_max_days = max(zero_buffer_max_days, result.days)

    risk_adjusted = route_eta_days + zero_buffer_max_days

    if scored == 0:
        rationale = (
            "No BOM line could be scored by the lead-time model "
            f"({declined_reason or unavailable_reason or 'no model loaded'}). "
            "Delivery ETA is route-derived (distributor handling + ground transit); "
            "no factory-lead-time risk is claimed."
        )
    elif zero_buffer_lines:
        rationale = (
            f"Longest factory lead time in this plan is {max_days:.0f} d ({driver_mpn}). "
            f"{zero_buffer_lines} line(s) take 100% of a distributor's reported shelf, so a "
            f"stale inventory snapshot would push the balance onto factory lead time: "
            f"risk-adjusted ETA {risk_adjusted:.1f} d vs {route_eta_days:.1f} d shipping from stock."
        )
    else:
        rationale = (
            f"Longest factory lead time among the {scored} scored line(s) is {max_days:.0f} d "
            f"({driver_mpn}) — that is the replenishment exposure, not this shipment's ETA. "
            f"Every line ships from stock with buffer remaining, so the ETA stays at "
            f"{route_eta_days:.1f} d."
        )
    if declined:
        rationale += (
            f" {declined} line(s) were declined by the model rather than guessed "
            f"({declined_reason})."
        )

    return schemas.SupplyRiskInfo(
        model_available=scored > 0,
        model_name=model_name,
        model_source=model_source_name,
        lines_scored=scored,
        lines_declined=declined,
        declined_reason=declined_reason,
        max_factory_lead_time_days=round(max_days, 1) if max_days is not None else None,
        driver_mpn=driver_mpn,
        zero_buffer_lines=zero_buffer_lines,
        route_eta_days=round(route_eta_days, 2),
        risk_adjusted_eta_days=round(risk_adjusted, 2),
        rationale=rationale,
    )


def _build_route_data(
    sourcing: SourcingResult,
    distributors: Dict[int, DistributorMeta],
    depot: GeoPoint,
) -> tuple:
    """Build weight/cost maps, TSP tour (domestic only), and direct metrics.

    Domestic distributors: included in the TSP truck tour.
    International distributors: modelled as direct air freight shipments
      (flat IATA base + per-kg rate) that arrive in parallel with the truck tour.
      A PCB manufacturer orders internationally by air — the truck never goes to
      China. This avoids applying LTL trucking rates to transatlantic distances.
    """
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

    domestic_dids = [did for did in sourcing.selected_distributor_ids if distributors[did].is_domestic]
    intl_dids = [did for did in sourcing.selected_distributor_ids if not distributors[did].is_domestic]

    # TSP tour over domestic distributors only
    nodes: List[RoutingNode] = []
    for did in domestic_dids:
        d = distributors[did]
        nodes.append(RoutingNode(id=did, lat=d.lat, lng=d.lng, name=d.name))
    tsp_order = solve_pickup_tsp(depot, nodes)
    ordered_nodes = [next(n for n in nodes if n.id == did) for did in tsp_order]

    # Shipments for cross-dock evaluation — domestic only (makes sense to consolidate)
    shipments_by_did: Dict[int, DistributorShipment] = {}
    for did in domestic_dids:
        d = distributors[did]
        shipments_by_did[did] = DistributorShipment(
            distributor_id=did, distributor_name=d.name,
            lat=d.lat, lng=d.lng,
            weight_kg=max(weight_by_did[did], 0.1),
            distributor_tier=d.tier,
        )
    shipments_list = list(shipments_by_did.values())
    domestic_metrics = evaluate_direct(depot, ordered_nodes, shipments_by_did)

    # Air freight cost and lead time for international distributors.
    # Runs in parallel with the domestic truck tour; total time = max(domestic, intl).
    AIR_TRANSIT_DAYS = 4  # handling (2d) + air (2d) — IATA standard commercial
    # ICAO 2023: dedicated freighter ~0.5 kg CO2e per tonne-km
    # = 0.0005 kg CO2e per kg per km
    CO2_AIR_KG_PER_KG_KM = 0.0005
    intl_cost = 0.0
    intl_co2 = 0.0
    intl_time = 0.0
    for did in intl_dids:
        d = distributors[did]
        w = max(weight_by_did.get(did, 0.0), 0.1)
        dist_km = haversine_km(depot.lat, depot.lng, d.lat, d.lng)
        intl_cost += AIR_FREIGHT_BASE_USD + w * AIR_FREIGHT_RATE_USD_PER_KG
        intl_co2 += w * dist_km * CO2_AIR_KG_PER_KG_KM
        intl_time = AIR_TRANSIT_DAYS

    direct_metrics = RouteMetrics(
        cost_usd=domestic_metrics.cost_usd + intl_cost,
        lead_time_days=max(domestic_metrics.lead_time_days, intl_time),
        co2_kg=domestic_metrics.co2_kg + intl_co2,
    )

    # For the ordered_nodes list used to build route stops, include intl distributors
    # as virtual nodes (they don't affect the truck tour but appear in the UI).
    intl_nodes = [RoutingNode(id=did, lat=distributors[did].lat, lng=distributors[did].lng,
                               name=distributors[did].name) for did in intl_dids]

    return (weight_by_did, cost_by_did, components_by_did,
            ordered_nodes, shipments_by_did, shipments_list, direct_metrics,
            intl_nodes, intl_cost)


def optimize_bom(
    bom: List[BomLine],
    offers: List[Offer],
    distributors: Dict[int, DistributorMeta],
    depot: GeoPoint,
    us_only: bool = False,
    graph_aware: bool = False,
    require_dual_source: bool = False,
) -> schemas.MultiRouteResponse:
    """Run all 4 strategies and return a MultiRouteResponse.

    require_dual_source: pass-through to the Stage 1 sourcing MILP; when True
    each strategy's plan is forced to spread the BOM across ≥2 distributors
    (hard diversification) instead of consolidating onto one cheapest hub.
    """
    if not bom:
        raise ValueError("BOM is empty")

    # ── Stage 1: per-strategy sourcing solve, cached by us_only flag.
    # Strategies with different us_only_sourcing get different supplier pools,
    # which is the primary driver of divergence (cheapest picks global, fastest
    # picks domestic for lower handling times).
    sourcing_cache: Dict[bool, SourcingResult] = {}
    all_outlier_drops = []

    def _get_sourcing(strat) -> SourcingResult:
        # Cache key: all MILP-influencing parameters must be included.
        # transport_penalty_scale and consolidation_bonus_usd both affect the
        # MILP objective; strategies with any differing value run separate solves.
        cache_key = (
            strat.us_only_sourcing or us_only,
            getattr(strat, "transport_penalty_scale", 1.0),
            getattr(strat, "consolidation_bonus_usd", 1.0),
        )
        if cache_key not in sourcing_cache:
            result = solve_sourcing(
                bom, offers, strat, us_only=cache_key[0],
                graph_aware=graph_aware, require_dual_source=require_dual_source,
            )
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
         direct_metrics, intl_nodes, intl_transport_cost) = _build_route_data(sourcing, distributors, depot)

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
            "intl_nodes": intl_nodes,
            "intl_transport_cost": intl_transport_cost,
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

        # Build route stops.
        # Domestic distributors: truck tour with LTL per-leg cost.
        # International distributors: air freight (fixed cost, no truck leg distance).
        intl_nodes_r: List[RoutingNode] = r["intl_nodes"]
        intl_transport_cost_r: float = r["intl_transport_cost"]
        stops: List[schemas.RouteStop] = []
        domestic_weight = max(sum(
            weight_by_did.get(n.id, 0.0) for n in ordered_nodes
        ), 0.1)
        intl_count = len(intl_nodes_r)
        seq = 0
        prev_lat, prev_lng = depot.lat, depot.lng
        for node in ordered_nodes:
            d = distributors[node.id]
            dist_km = haversine_km(prev_lat, prev_lng, node.lat, node.lng)
            leg_cost = transport_cost_usd(dist_km, domestic_weight)
            leg_co2 = co2_kg(dist_km, domestic_weight)
            seq += 1
            stops.append(schemas.RouteStop(
                order=seq,
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

        # Return-to-depot leg (truck tour)
        if ordered_nodes:
            last_node = ordered_nodes[-1]
            ret_km = haversine_km(last_node.lat, last_node.lng, depot.lat, depot.lng)
            ret_cost = transport_cost_usd(ret_km, domestic_weight)
            ret_co2 = co2_kg(ret_km, domestic_weight)
            seq += 1
            stops.append(schemas.RouteStop(
                order=seq,
                distributor_id=0,
                distributor_name="Factory (Depot)",
                city=None, state=None, country="USA",
                lat=depot.lat, lng=depot.lng,
                components=[],
                distance_km=round(ret_km, 1),
                leg_cost_usd=round(ret_cost, 2),
                leg_co2e_kg=round(ret_co2, 3),
            ))

        # Air freight stops for international distributors (shown as separate legs)
        air_per_intl = intl_transport_cost_r / max(len(intl_nodes_r), 1)
        for node in intl_nodes_r:
            d = distributors[node.id]
            w = max(weight_by_did.get(node.id, 0.0), 0.1)
            af_dist_km = haversine_km(depot.lat, depot.lng, d.lat, d.lng)
            af_cost = AIR_FREIGHT_BASE_USD + w * AIR_FREIGHT_RATE_USD_PER_KG
            af_co2 = w * af_dist_km * 0.0005  # ICAO 2023: 0.5 kg CO2e/tonne-km
            seq += 1
            stops.append(schemas.RouteStop(
                order=seq,
                distributor_id=node.id,
                distributor_name=d.name,
                city=d.city, state=d.state, country=d.country,
                lat=d.lat, lng=d.lng,
                components=components_by_did.get(node.id, []),
                distance_km=0.0,  # air freight — distance not meaningful
                leg_cost_usd=round(af_cost, 2),
                leg_co2e_kg=round(af_co2, 3),
            ))

        # Totals.  transport_cost is derived from the displayed route stops so
        # that sum(leg_cost_usd) == total_transport_cost_usd exactly.  ETA and
        # CO2 come from the strategy metrics m (which includes cross-dock gains
        # when the hub route is faster/greener than the direct tour).
        component_cost = sum(cost_by_did.values())
        transport_cost = round(sum(s.leg_cost_usd for s in stops), 2)
        holding = holding_cost_usd(component_cost, m.lead_time_days)
        total_cost = component_cost + transport_cost + holding

        if ordered_nodes:
            rep_node = ordered_nodes[len(ordered_nodes) // 2]

        # ── ML factory lead time → supply-risk read-out (NOT the delivery ETA) ──
        #
        # This used to read: predict one ML lead time for a made-up
        # ("Microcontrollers", median distance, risk 0.5, coverage 10.0) row and
        # SWAP it in for the route ETA if
        #     |ml - route| / route > 0.10  and  ml < route * 2
        # Because the served model was a constant 62.1 d (see lead_time_model.py)
        # and `route_eta` never exceeded 16.4 d across all 234 recorded runs, the
        # second clause required route_eta > 31.05 d and the branch fired 0/234
        # times. Fixing the threshold would not have made it right: the model
        # predicts FACTORY lead time (time to replenish a part) while route_eta
        # is handling + transit for a unit shipping off the shelf. The sourcing
        # MILP hard-constrains ordered_qty <= offer.stock, so the delivery ETA of
        # the plan it produces genuinely IS route-derived.
        #
        # So the model now answers the question it was trained to answer, per BOM
        # line, using that line's real category / stock / price — and it is
        # reported as its own quantity instead of overwriting the ETA.
        route_eta = m.lead_time_days
        supply_risk = _assess_supply_risk(sourcing, bom, offers, route_eta)
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
            total_co2e_kg=round(sum(s.leg_co2e_kg for s in stops), 3),
            total_distance_km=round(sum(s.distance_km for s in stops), 1),
            base_eta_days=round(m.lead_time_days, 1),
            eta_p10=mc["p10"], eta_p50=mc["p50"], eta_p90=mc["p90"],
            monte_carlo_samples=mc["samples"],
            stop_count=len(stops),
            international_stops=intl_count,
            cost_breakdown=cost_breakdown,
            strategy_math=strategy_math,
            cross_dock=cd_info,
            supply_risk=supply_risk,
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
