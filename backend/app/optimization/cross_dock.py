"""
Cross-dock consolidation analysis.

For each candidate hub, compute:
  - N LTL legs (distributor → hub)
  - 1 consolidated leg (hub → depot, TL if ≥10,000 lbs)
  - Hub handling fee + dwell time
Pick the hub that minimizes the weighted objective — but only if it
beats direct pickup by ≥5% (the improvement threshold avoids pointless
hub trips when gains are marginal).

This is Lagrangian relaxation of the Capacitated Facility Location
Problem (Daskin 2013, Ch. 4) — with only 10 candidate hubs enumeration
is exact and trivially fast.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.optimization.costs import (
    HUB_DWELL_DAYS, HUB_HANDLING_FEE_USD,
    co2_kg, haversine_km, leg_lead_time_days, transit_days,
    transport_cost_usd,
)
from app.optimization.freight_hubs import FREIGHT_HUBS, FreightHub
from app.optimization.routing import GeoPoint, RoutingNode
from app.optimization.strategies import StrategyWeights


CROSS_DOCK_IMPROVEMENT_THRESHOLD = 0.95  # hub must beat direct by ≥ 5%


@dataclass(frozen=True)
class DistributorShipment:
    distributor_id: int
    distributor_name: str
    lat: float
    lng: float
    weight_kg: float
    distributor_tier: str  # 'major'|'mid'|'broker'


@dataclass(frozen=True)
class RouteMetrics:
    cost_usd: float
    lead_time_days: float
    co2_kg: float


@dataclass(frozen=True)
class CrossDockDecision:
    enabled: bool
    hub: Optional[FreightHub]
    direct_metrics: RouteMetrics
    consolidated_metrics: Optional[RouteMetrics]
    savings_vs_direct_pct: float
    rationale: str


def _weighted_objective(metrics: RouteMetrics, weights: StrategyWeights) -> float:
    """
    Single-alternative weighted objective (no normalization — used only for
    direct-vs-consolidated comparison within one strategy).
    """
    return (
        weights.w_cost * metrics.cost_usd
        + weights.w_time * metrics.lead_time_days * 100.0  # hours-worth scale
        + weights.w_carbon * metrics.co2_kg * 10.0
    )


def evaluate_hub(
    hub: FreightHub,
    depot: GeoPoint,
    shipments: List[DistributorShipment],
) -> RouteMetrics:
    """
    Compute cost/time/CO2 for consolidating all shipments at this hub.

    N LTL legs distributor → hub, then 1 consolidated leg hub → depot.
    """
    total_cost = HUB_HANDLING_FEE_USD
    total_co2 = 0.0
    max_leg_time = 0.0
    total_weight = 0.0

    for s in shipments:
        d_km = haversine_km(s.lat, s.lng, hub.latitude, hub.longitude)
        total_cost += transport_cost_usd(d_km, s.weight_kg)
        total_co2 += co2_kg(d_km, s.weight_kg)
        leg_time = leg_lead_time_days(d_km, s.distributor_tier)
        if leg_time > max_leg_time:
            max_leg_time = leg_time
        total_weight += s.weight_kg

    # Consolidated hub → depot leg
    d_hub_depot_km = haversine_km(hub.latitude, hub.longitude, depot.lat, depot.lng)
    total_cost += transport_cost_usd(d_hub_depot_km, total_weight)
    total_co2 += co2_kg(d_hub_depot_km, total_weight)
    consolidated_leg_time = transit_days(d_hub_depot_km)

    total_time = max_leg_time + HUB_DWELL_DAYS + consolidated_leg_time

    return RouteMetrics(cost_usd=total_cost, lead_time_days=total_time, co2_kg=total_co2)


def evaluate_direct(
    depot: GeoPoint,
    ordered_nodes: List[RoutingNode],
    shipments_by_did: dict,
) -> RouteMetrics:
    """
    Compute cost/time/CO2 for the direct pickup tour.

    A single truck drives depot → d1 → d2 → ... → depot carrying the
    cumulative load. We model this as a sequence of LTL-or-TL legs.
    """
    if not ordered_nodes:
        return RouteMetrics(0.0, 0.0, 0.0)

    total_cost = 0.0
    total_co2 = 0.0
    total_time = 0.0
    cumulative_weight = sum(s.weight_kg for s in shipments_by_did.values())

    prev = (depot.lat, depot.lng)
    for node in ordered_nodes:
        s = shipments_by_did[node.id]
        d_km = haversine_km(prev[0], prev[1], node.lat, node.lng)
        total_cost += transport_cost_usd(d_km, cumulative_weight)
        total_co2 += co2_kg(d_km, cumulative_weight)
        total_time += leg_lead_time_days(d_km, s.distributor_tier)
        prev = (node.lat, node.lng)

    # Return leg depot
    d_km = haversine_km(prev[0], prev[1], depot.lat, depot.lng)
    total_cost += transport_cost_usd(d_km, cumulative_weight)
    total_co2 += co2_kg(d_km, cumulative_weight)
    total_time += transit_days(d_km)

    return RouteMetrics(cost_usd=total_cost, lead_time_days=total_time, co2_kg=total_co2)


def evaluate_cross_dock(
    direct: RouteMetrics,
    shipments: List[DistributorShipment],
    depot: GeoPoint,
    weights: StrategyWeights,
    hubs: List[FreightHub] = None,
) -> CrossDockDecision:
    """Enumerate hubs, pick the best — or reject if it doesn't clear the threshold."""
    if hubs is None:
        hubs = FREIGHT_HUBS

    # Cross-dock requires at least 2 distributors to make sense
    if len(shipments) < 2:
        return CrossDockDecision(
            enabled=False, hub=None, direct_metrics=direct,
            consolidated_metrics=None, savings_vs_direct_pct=0.0,
            rationale="single-distributor route — no consolidation benefit",
        )

    direct_obj = _weighted_objective(direct, weights)
    best_hub: Optional[FreightHub] = None
    best_metrics: Optional[RouteMetrics] = None
    best_obj = float("inf")

    for hub in hubs:
        m = evaluate_hub(hub, depot, shipments)
        obj = _weighted_objective(m, weights)
        if obj < best_obj:
            best_obj = obj
            best_metrics = m
            best_hub = hub

    if best_hub is None or best_metrics is None:
        return CrossDockDecision(
            enabled=False, hub=None, direct_metrics=direct,
            consolidated_metrics=None, savings_vs_direct_pct=0.0,
            rationale="no hubs provided",
        )

    # 5% improvement threshold
    if best_obj >= CROSS_DOCK_IMPROVEMENT_THRESHOLD * direct_obj:
        return CrossDockDecision(
            enabled=False, hub=best_hub, direct_metrics=direct,
            consolidated_metrics=best_metrics,
            savings_vs_direct_pct=round(100.0 * (1.0 - best_obj / direct_obj), 2),
            rationale=f"hub {best_hub.city} beat direct by "
                      f"{100*(1-best_obj/direct_obj):.1f}% < 5% threshold",
        )

    savings_pct = round(100.0 * (1.0 - best_obj / direct_obj), 2)
    return CrossDockDecision(
        enabled=True, hub=best_hub, direct_metrics=direct,
        consolidated_metrics=best_metrics,
        savings_vs_direct_pct=savings_pct,
        rationale=f"consolidating via {best_hub.city} saves {savings_pct}% "
                  f"on the weighted objective",
    )
