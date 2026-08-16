"""
Pydantic response models for the optimization pipeline.

Additive to the existing RouteAlternative shape — the frontend only
reads new fields when present.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel


class BomLine(BaseModel):
    component_id: int
    mpn: str
    quantity: int


class OfferRef(BaseModel):
    component_id: int
    distributor_id: int
    price_usd: float
    stock: int
    moq: int


class SourcingAssignment(BaseModel):
    component_id: int
    mpn: str
    distributor_id: int
    distributor_name: str
    quantity: int
    unit_price_usd: float
    line_total_usd: float


class RouteStop(BaseModel):
    order: int
    distributor_id: int
    distributor_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    lat: float
    lng: float
    components: List[str]
    distance_km: float
    leg_cost_usd: float
    leg_co2e_kg: float


class CostBreakdown(BaseModel):
    component_cost: float
    transport_cost: float
    holding_cost: float
    total: float


class StrategyMath(BaseModel):
    weights: Dict[str, float]               # {cost, time, carbon}
    raw_objective_values: Dict[str, float]  # {cost, time, carbon}
    normalized_objective_values: Dict[str, float]
    weighted_total: float
    citations: List[str]


class CrossDockInfo(BaseModel):
    enabled: bool
    hub_id: Optional[int] = None
    hub_name: Optional[str] = None
    hub_city: Optional[str] = None
    hub_state: Optional[str] = None
    hub_lat: Optional[float] = None
    hub_lng: Optional[float] = None
    savings_vs_direct_pct: float = 0.0
    direct_cost_usd: float = 0.0
    consolidated_cost_usd: float = 0.0
    rationale: str = ""


class SupplyRiskInfo(BaseModel):
    """ML factory-lead-time read-out for a sourcing plan.

    This is the *only* place the lead-time model touches the optimizer output,
    and it is deliberately separate from ``eta_p50``. The model predicts the
    FACTORY (replenishment) lead time a distributor publishes for a part; the
    route ETA is handling + ground transit for units that ship from stock. The
    sourcing MILP enforces ``ordered_qty <= offer.stock`` on every assignment, so
    the shipped plan really does ship from stock and its ETA really is
    route-derived. Overwriting the route ETA with the factory lead time — which
    is what this code did before 2026-08-15, behind a gate that could never fire
    — conflated two different quantities.

    ``risk_adjusted_eta_days`` is the conservative read: for lines where the plan
    takes 100% of a distributor's reported shelf (zero buffer), a stale inventory
    snapshot means the balance would come off the factory lead time instead.
    """
    model_available: bool
    model_name: Optional[str] = None
    model_source: Optional[str] = None        # mlflow_registry | local_joblib | none
    lines_scored: int = 0                     # BOM lines the model could price
    lines_declined: int = 0                   # lines outside the trained category vocabulary
    declined_reason: Optional[str] = None
    max_factory_lead_time_days: Optional[float] = None
    driver_mpn: Optional[str] = None          # the longest-lead part in the plan
    zero_buffer_lines: int = 0                # lines that consume a distributor's whole shelf
    route_eta_days: float = 0.0               # handling + transit, ships-from-stock
    risk_adjusted_eta_days: float = 0.0       # route_eta + factory LT on zero-buffer lines
    rationale: str = ""


class OutlierDropLog(BaseModel):
    component_id: int
    mpn: str
    dropped_distributor_id: int
    dropped_price_usd: float
    median_price_usd: float
    reason: str


class RouteAlternative(BaseModel):
    id: str
    label: str
    description: str
    route: List[RouteStop]
    sourcing: List[SourcingAssignment]
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
    # New fields (optional — frontend reads if present)
    cost_breakdown: Optional[CostBreakdown] = None
    strategy_math: Optional[StrategyMath] = None
    cross_dock: Optional[CrossDockInfo] = None
    supply_risk: Optional[SupplyRiskInfo] = None


class MultiRouteResponse(BaseModel):
    alternatives: List[RouteAlternative]
    recommended_id: str
    outlier_drops: List[OutlierDropLog] = []
