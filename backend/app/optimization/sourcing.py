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

    # Objective: minimize total component cost (scaled to cents)
    # + small bonus for fewer distributor visits (tiebreak favoring consolidation)
    cost_terms = []
    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            price_cents = int(round(o.price_usd * PRICE_SCALE))
            cost_terms.append(price_cents * q[key])
    # Tiny stop penalty: $1 per distributor visited (scaled), acts as tiebreaker
    stop_penalty = sum(y[did] * PRICE_SCALE for did in y)
    model.Minimize(sum(cost_terms) + stop_penalty)

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
