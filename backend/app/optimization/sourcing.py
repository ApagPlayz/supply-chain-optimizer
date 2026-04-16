"""
Stage 1 — Component sourcing integer program.

Outlier filter + CP-SAT MILP. See spec §3.2 and §5.4.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from app.optimization.constants import (
    LTL_BASE_FEE_USD as LTL_BASE,
    LTL_RATE_USD_PER_CWT_MILE as LTL_RATE,
    KM_PER_MILE,
    LBS_PER_KG,
    CWT_PER_LB,
)
from app.optimization.strategies import StrategyWeights

logger = logging.getLogger(__name__)


# ── Data containers ──────────────────────────────────────────────────────────

@dataclass
class BomLine:
    component_id: int
    mpn: str
    quantity: int


@dataclass
class Offer:
    component_id: int
    distributor_id: int
    distributor_name: str
    price_usd: float
    stock: int
    moq: int
    is_domestic: bool
    dist_km_from_depot: float = 0.0  # precomputed haversine; used for transport penalty
    risk_score: float = 0.5           # component risk (0-1, from Nexar)
    is_chinese_origin: bool = False   # True if manufacturer_country is China


@dataclass
class OutlierDrop:
    component_id: int
    mpn: str
    dropped_distributor_id: int
    dropped_price_usd: float
    median_price_usd: float
    reason: str


@dataclass
class SourcingAssignment:
    component_id: int
    mpn: str
    distributor_id: int
    distributor_name: str
    quantity: int
    unit_price_usd: float

    @property
    def line_total(self) -> float:
        return self.quantity * self.unit_price_usd


@dataclass
class SourcingResult:
    assignments: List[SourcingAssignment]
    total_component_cost: float
    selected_distributor_ids: List[int]
    outlier_drops: List[OutlierDrop] = field(default_factory=list)
    status: str = "OPTIMAL"


# ── Outlier filter ───────────────────────────────────────────────────────────

OUTLIER_MEDIAN_MULTIPLE = 5.0  # Aberdeen Group 2020


def filter_price_outliers(
    offers: List[Offer],
    bom: List[BomLine],
    k: float = OUTLIER_MEDIAN_MULTIPLE,
) -> Tuple[List[Offer], List[OutlierDrop]]:
    """
    Drop offers where price > k * median(price) for that component.

    One-sided — low prices (real discounts) are kept. See spec §5.4.
    """
    mpn_by_id = {b.component_id: b.mpn for b in bom}
    by_component: Dict[int, List[Offer]] = {}
    for o in offers:
        by_component.setdefault(o.component_id, []).append(o)

    kept: List[Offer] = []
    drops: List[OutlierDrop] = []

    for cid, group in by_component.items():
        prices = [o.price_usd for o in group if o.price_usd > 0]
        if not prices:
            continue
        median = statistics.median(prices)
        cutoff = k * median
        for o in group:
            if o.price_usd > cutoff:
                drops.append(OutlierDrop(
                    component_id=cid,
                    mpn=mpn_by_id.get(cid, f"component_{cid}"),
                    dropped_distributor_id=o.distributor_id,
                    dropped_price_usd=o.price_usd,
                    median_price_usd=median,
                    reason=f"price {o.price_usd:.2f} > {k}×median {median:.2f}",
                ))
                logger.info("outlier dropped: cid=%s did=%s price=%.2f median=%.2f",
                            cid, o.distributor_id, o.price_usd, median)
            else:
                kept.append(o)
    return kept, drops


# ── CP-SAT sourcing MILP ─────────────────────────────────────────────────────

# Scale factor: CP-SAT wants integer coefficients. Prices stored as cents.
PRICE_SCALE = 100


def _stockout_risk_premium_cents(
    offer: "Offer",
    bom_line: "BomLine",
    macro_stress: float,
) -> int:
    """
    Compute a risk surcharge in cents to add to the MILP effective price.

    Formula:
        vulnerability = 0.3×is_chinese_origin + 0.2×(1 - min(stock_coverage,50)/50) + 0.5×risk_score
        stockout_risk = macro_stress × vulnerability
        surcharge     = unit_price × stockout_risk × RISK_PREMIUM_RATE

    RISK_PREMIUM_RATE = 0.15: a 15% effective price uplift at max combined risk.
    This is calibrated so that even at maximum stress+vulnerability, the surcharge
    (~15% of unit price) does not override large genuine cost differences —
    it only tips the balance between otherwise comparable offers.

    Returns integer cents (scaled by PRICE_SCALE=100).
    """
    RISK_PREMIUM_RATE = 0.15

    is_chinese = getattr(offer, "is_chinese_origin", False)
    risk_score = getattr(offer, "risk_score", 0.5)
    stock = offer.stock or 0
    moq = offer.moq or 1
    stock_coverage = min(stock / max(moq, 1), 50.0)

    vulnerability = (
        0.3 * int(is_chinese)
        + 0.2 * (1.0 - stock_coverage / 50.0)
        + 0.5 * float(risk_score)
    )
    stockout_risk = macro_stress * vulnerability
    surcharge_usd = offer.price_usd * stockout_risk * RISK_PREMIUM_RATE
    return int(round(surcharge_usd * PRICE_SCALE))


def solve_sourcing(
    bom: List[BomLine],
    offers: List[Offer],
    weights: StrategyWeights,
    us_only: bool = True,
) -> SourcingResult:
    """
    Pick which distributor fills each BOM line (and how much) to minimize
    cost, subject to demand/stock/MOQ/domestic constraints.

    The Stage 1 MILP minimizes only component cost. Time and carbon are
    distance-dependent and are evaluated in Stage 2 (TSP) and composed with
    the Stage 1 result in the orchestrator (solve.py).
    """
    # Pre-filter outliers
    offers, drops = filter_price_outliers(offers, bom)

    # Pre-filter by us_only
    if us_only:
        offers = [o for o in offers if o.is_domestic]

    # Group by component
    offers_by_component: Dict[int, List[Offer]] = {}
    for o in offers:
        offers_by_component.setdefault(o.component_id, []).append(o)

    # Validate every BOM line has at least one offer after filtering
    missing = [b.mpn for b in bom if not offers_by_component.get(b.component_id)]
    if missing:
        raise ValueError(
            f"No valid offers for components after filtering: {missing}"
        )

    model = cp_model.CpModel()

    # x[cid, did] ∈ {0,1} — select this offer
    # q[cid, did] ∈ [0, stock] — quantity ordered
    # y[did] ∈ {0,1} — visit this distributor
    x: Dict[Tuple[int, int], cp_model.IntVar] = {}
    q: Dict[Tuple[int, int], cp_model.IntVar] = {}
    y: Dict[int, cp_model.IntVar] = {}

    all_distributors = {o.distributor_id for o in offers}
    for did in all_distributors:
        y[did] = model.NewBoolVar(f"y_{did}")

    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            x[key] = model.NewBoolVar(f"x_c{b.component_id}_d{o.distributor_id}")
            # Quantity bounded by stock and demand
            upper = min(o.stock, b.quantity)
            q[key] = model.NewIntVar(0, max(upper, 0), f"q_c{b.component_id}_d{o.distributor_id}")

    for b in bom:
        # Demand coverage: sum of quantities over offers == demand
        model.Add(
            sum(q[(b.component_id, o.distributor_id)]
                for o in offers_by_component[b.component_id]) == b.quantity
        )
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            # Stock cap: q ≤ stock * x
            model.Add(q[key] <= o.stock * x[key])
            # MOQ floor: if x=1, q ≥ moq; if x=0, q=0 (already enforced by stock cap)
            if o.moq > 1:
                model.Add(q[key] >= o.moq * x[key])
            else:
                model.Add(q[key] >= x[key])  # q ≥ 1 if selected
            # Distributor linking: y ≥ x
            model.Add(y[o.distributor_id] >= x[key])

    # Objective: minimize total component cost + transport penalty per distributor.
    #
    # Transport penalty: estimated one-way freight cost to visit a distributor,
    # derived from its haversine distance from the depot.  The LTL rate is
    # applied to a representative BOM weight (avg qty × component weight) so
    # that distant international distributors are correctly penalised relative
    # to nearby domestic ones.
    #
    # penalty_scale (from StrategyWeights.transport_penalty_scale):
    #   cheapest  = 1.0  → full transport cost in objective (landed cost)
    #   fastest   = 0.0  → us_only filter handles distance; no extra penalty
    #   greenest  = 2.5  → strong proximity preference to cut tonne-miles CO2
    #   balanced  = 1.2  → moderate distance penalty
    #
    # Freight constants are imported from app.optimization.constants at module top.
    AVG_KG_PER_UNIT = 0.05

    # Representative per-distributor shipment weight: average BOM demand × kg/unit
    avg_demand = sum(b.quantity for b in bom) / max(len(bom), 1)
    avg_weight_kg = avg_demand * AVG_KG_PER_UNIT

    # Precompute estimated transport cost per distributor visit
    transport_cost_by_did: Dict[int, float] = {}
    dist_km_by_did = {o.distributor_id: o.dist_km_from_depot for o in offers}
    for did in all_distributors:
        km = dist_km_by_did.get(did, 0.0)
        miles = km / KM_PER_MILE
        cwt = avg_weight_kg * LBS_PER_KG * CWT_PER_LB
        transport_cost_by_did[did] = LTL_BASE + cwt * miles * LTL_RATE

    penalty_scale = getattr(weights, "transport_penalty_scale", 1.0)

    cost_terms = []
    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            price_cents = int(round(o.price_usd * PRICE_SCALE))
            cost_terms.append(price_cents * q[key])

    transport_terms = []
    for did in all_distributors:
        est_transport_cents = int(round(
            transport_cost_by_did[did] * penalty_scale * PRICE_SCALE
        ))
        transport_terms.append(est_transport_cents * y[did])

    consolidation_bonus = getattr(weights, "consolidation_bonus_usd", 1.0)
    consolidation_terms = [
        int(round(consolidation_bonus * PRICE_SCALE)) * y[did]
        for did in all_distributors
    ]
    # ── Risk surcharge terms ──────────────────────────────────────────────────
    # Stock-out risk premium from macro stress model.
    # Falls back to 0 if ML state not loaded (no penalty applied).
    from app.ml import get_ml_state  # local import to avoid circular dep at module load
    _ml = get_ml_state()
    macro_stress = _ml.current_stress_prob if _ml is not None else 0.0

    risk_terms = []
    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            premium = _stockout_risk_premium_cents(o, b, macro_stress)
            if premium > 0:
                risk_terms.append(premium * x[key])

    model.Minimize(sum(cost_terms) + sum(transport_terms) + sum(consolidation_terms) + sum(risk_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"Sourcing MILP infeasible (status={solver.StatusName(status)})"
        )

    # Extract assignments
    assignments: List[SourcingAssignment] = []
    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            qty = solver.Value(q[key])
            if qty > 0:
                assignments.append(SourcingAssignment(
                    component_id=b.component_id,
                    mpn=b.mpn,
                    distributor_id=o.distributor_id,
                    distributor_name=o.distributor_name,
                    quantity=qty,
                    unit_price_usd=o.price_usd,
                ))

    total_cost = sum(a.line_total for a in assignments)
    selected = sorted({a.distributor_id for a in assignments})

    return SourcingResult(
        assignments=assignments,
        total_component_cost=total_cost,
        selected_distributor_ids=selected,
        outlier_drops=drops,
        status=solver.StatusName(status),
    )
