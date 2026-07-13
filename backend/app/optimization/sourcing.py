"""
Stage 1 — Component sourcing integer program.

Outlier filter + CP-SAT MILP. See spec §3.2 and §5.4.
"""
from __future__ import annotations

import logging
import math
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
    AIR_FREIGHT_BASE_USD,
    AIR_FREIGHT_RATE_USD_PER_KG,
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
    distributor_country: str = "US"   # ISO country code of distributor warehouse


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
    # The solver's own objective value, converted back to USD (objective units /
    # OBJ_SCALE). None for the greedy baselines, which have no solver objective.
    # greedy.landed_cost_breakdown() must reproduce this to within integer
    # rounding — that agreement is the benchmark's anti-rigging invariant.
    objective_usd: Optional[float] = None


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
            logger.warning(
                "component_id=%s has no offers with price > 0; skipping outlier filter and keeping all offers",
                cid,
            )
            kept.extend(group)
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

# The objective is built in integer MILLI-CENTS (PRICE_SCALE x OBJ_SUBSCALE).
# Every term is multiplied by the same constant, so the argmin is identical to a
# cents-denominated objective — but the per-unit freight rate is a genuinely
# small number (~$0.029/unit at 100 km, ~$0.003/unit at 10 km). In whole cents it
# would round to ZERO for nearby distributors and the variable freight term would
# silently vanish. Milli-cent resolution keeps it.
OBJ_SUBSCALE = 1000
OBJ_SCALE = PRICE_SCALE * OBJ_SUBSCALE  # objective units per USD

# Average shipped mass of one electronic component unit. Used to turn "units
# shipped" into freight-chargeable weight.
AVG_KG_PER_UNIT = 0.05


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


# Snyder & Daskin (2005), "Reliable Location Models" — a disrupted
# single-sourced component has no cheaper fallback offer to price a delta
# against, so its expected recourse cost is approximated as a large-but-
# finite multiple of unit price (stand-in for expediting/respin cost).
STOCKOUT_PENALTY_MULTIPLE = 3.0

# Emergency-reprocurement premium: even when a substitute exists, recovering a
# disrupted line means expediting the replacement units at a premium. Mirrors the
# Monte Carlo model's EMERGENCY_COST_PREMIUM (0.15). Defined locally so the
# optimization layer stays independent of the graph/simulation layer.
EMERGENCY_REPROCURE_PREMIUM = 0.15


def _graph_surcharge_cents(
    offer: "Offer",
    betweenness_score: float,
    component_offers: List["Offer"],
) -> int:
    """
    Expected-disruption-loss surcharge in cents (Snyder & Daskin 2005 reliable
    facility location): surcharge = P(disruption) x expected recourse loss.

    p_d = betweenness_score — structural concentration proxy for this
    distributor; higher betweenness means more of the network's flow depends on
    this node, i.e. a higher disruption probability.

    recourse_cost_cents = the expected per-unit loss if this source is disrupted:
      - the price gap to switch to the next-cheapest alternative offer, PLUS
      - an emergency-reprocurement premium on the unit (EMERGENCY_REPROCURE_PREMIUM)
        for expediting the replacement — incurred even when a cheap substitute
        exists, because recovery is never free.
      If no alternative offer exists (single-source component), the recourse cost
      is a large-but-finite STOCKOUT_PENALTY_MULTIPLE x unit price (expedite/respin
      stand-in), which dominates the substitutable case as it should.

    surcharge_cents = round(p_d * recourse_cost_cents)

    Near-zero for low-centrality suppliers, and materially larger for
    high-centrality ones — so graph-aware sourcing is biased away from
    concentrated hubs toward lower-centrality alternatives (diversification),
    while a low-centrality plan pays essentially nothing. This is the true
    "insurance" shape, with no arbitrary flat-rate cap.
    """
    unit_price_cents = int(round(offer.price_usd * PRICE_SCALE))

    alt_prices_cents = [
        int(round(o.price_usd * PRICE_SCALE))
        for o in component_offers
        if o.distributor_id != offer.distributor_id
    ]
    if alt_prices_cents:
        next_cheapest_cents = min(alt_prices_cents)
        switch_gap_cents = max(0, next_cheapest_cents - unit_price_cents)
        expedite_cents = int(round(EMERGENCY_REPROCURE_PREMIUM * unit_price_cents))
        recourse_cost_cents = switch_gap_cents + expedite_cents
    else:
        recourse_cost_cents = int(round(STOCKOUT_PENALTY_MULTIPLE * unit_price_cents))

    return int(round(betweenness_score * recourse_cost_cents))


def _feed_risk_cents(
    offer: "Offer",
    distributor_country: str,
    is_chinese_origin: bool,
    cache: "object | None",
) -> int:
    """
    Feed-driven risk surcharge in cents. Per D-01 from CONTEXT.md.

    GPR: Chinese-origin component risk scaled by geopolitical tension.
    ACLED: distributor-country risk scaled by 90-day conflict count.

    Ceiling: 15% of unit price (matching graph surcharge ceiling).
    Returns 0 when cache is None or feed data unavailable.
    """
    import math
    if cache is None:
        return 0

    unit_price_cents = int(round(offer.price_usd * PRICE_SCALE))
    ceiling = int(math.floor(0.15 * unit_price_cents))

    gpr_surcharge = 0
    acled_surcharge = 0

    # GPR: Chinese-origin risk
    if is_chinese_origin and getattr(cache, 'gpr', None) is not None and cache.gpr.data is not None:
        gpr_value = float(cache.gpr.data)  # typically 50-500
        gpr_normalized = max(0.0, min((gpr_value - 100) / 400, 1.0))
        gpr_surcharge = int(math.floor(gpr_normalized * 0.15 * unit_price_cents))

    # ACLED: distributor country conflict risk
    if getattr(cache, 'acled', None) is not None and cache.acled.data is not None:
        country_counts = cache.acled.data
        # distributor_country might be "US", "CN", etc. — use as-is for lookup
        conflict_count = country_counts.get(distributor_country, 0)
        acled_normalized = min(conflict_count / 500, 1.0)
        acled_surcharge = int(math.floor(acled_normalized * 0.15 * unit_price_cents))

    total = gpr_surcharge + acled_surcharge
    return min(total, ceiling)


@dataclass(frozen=True)
class FreightModel:
    """
    Freight decomposed into the two parts a fixed-charge network model needs.

    fixed_by_did[d]     USD charged ONCE for opening distributor d — the LTL base
                        fee (domestic) or the air consignment minimum
                        (international). Does NOT depend on how much d ships.
                        This is the genuine fixed charge whose trade-off against
                        component price is the entire reason the MILP exists.

    per_unit_by_did[d]  USD per UNIT actually shipped from d — weight x distance
                        for domestic LTL, weight x $/kg for air. Scales with the
                        quantity d really ships, so splitting a BOM across N
                        suppliers ALLOCATES one BOM's variable freight among them
                        instead of charging a full BOM's freight N times over.

    Both components are already multiplied by penalty_scale
    (StrategyWeights.transport_penalty_scale), so they can be dropped straight
    into a cost objective (MILP or greedy baseline) with no further scaling:
      cheapest  = 1.0  → full transport cost in objective (landed cost)
      fastest   = 0.0  → us_only filter handles distance; no extra penalty
      greenest  = 2.5  → strong proximity preference to cut tonne-miles CO2
      balanced  = 1.2  → moderate distance penalty

    Total freight paid to distributor d:
        fixed_by_did[d] * opened(d) + per_unit_by_did[d] * units_shipped_from(d)

    which is linear in the CP-SAT decision variables (y[d] and sum_c q[c,d]), so
    the MILP models it exactly rather than approximating it.
    """
    fixed_by_did: Dict[int, float]
    per_unit_by_did: Dict[int, float]


def _freight_model_by_did(
    offers: List["Offer"],
    penalty_scale: float,
) -> FreightModel:
    """
    Build the per-distributor freight model (see FreightModel).

    Domestic: LTL tariff (FreightWaves SONAR Q4 2023 / Old Dominion) —
      fixed    = LTL_BASE_FEE_USD
      per unit = AVG_KG_PER_UNIT x LBS_PER_KG x CWT_PER_LB x miles x LTL_RATE
    International: IATA 2023 airfreight (flat consignment base + $/kg) —
      fixed    = AIR_FREIGHT_BASE_USD
      per unit = AVG_KG_PER_UNIT x AIR_FREIGHT_RATE_USD_PER_KG
    (LTL_RATE_USD_PER_CWT_MILE is domestic trucking only and produces absurd
    values over 6,000+ km international distances, hence the split.)

    This replaces an earlier model that computed ONE representative shipment
    weight for the whole BOM and then charged EVERY opened distributor that full
    weight. That replicated variable freight per supplier instead of allocating
    it, systematically over-penalising split orders and inflating the MILP's
    apparent consolidation advantage.
    """
    all_distributors = {o.distributor_id for o in offers}
    dist_km_by_did = {o.distributor_id: o.dist_km_from_depot for o in offers}
    is_domestic_by_did = {o.distributor_id: o.is_domestic for o in offers}

    fixed_by_did: Dict[int, float] = {}
    per_unit_by_did: Dict[int, float] = {}
    for did in all_distributors:
        km = dist_km_by_did.get(did, 0.0)
        if is_domestic_by_did.get(did, True):
            miles = km / KM_PER_MILE
            fixed = LTL_BASE
            per_unit = AVG_KG_PER_UNIT * LBS_PER_KG * CWT_PER_LB * miles * LTL_RATE
        else:
            fixed = AIR_FREIGHT_BASE_USD
            per_unit = AVG_KG_PER_UNIT * AIR_FREIGHT_RATE_USD_PER_KG
        fixed_by_did[did] = fixed * penalty_scale
        per_unit_by_did[did] = per_unit * penalty_scale

    return FreightModel(fixed_by_did=fixed_by_did, per_unit_by_did=per_unit_by_did)


def solve_sourcing(
    bom: List[BomLine],
    offers: List[Offer],
    weights: StrategyWeights,
    us_only: bool = True,
    graph_aware: bool = False,
    require_dual_source: bool = False,
) -> SourcingResult:
    """
    Pick which distributor fills each BOM line (and how much) to minimize
    cost, subject to demand/stock/MOQ/domestic constraints.

    The Stage 1 MILP minimizes only component cost. Time and carbon are
    distance-dependent and are evaluated in Stage 2 (TSP) and composed with
    the Stage 1 result in the orchestrator (solve.py).

    require_dual_source: when True (and the BOM has ≥2 lines), a HARD
    diversification constraint caps how many BOM lines any single distributor
    may source, forcing the plan to spread across ≥2 distributors so a targeted
    outage of the cheapest hub cannot orphan the whole BOM. The solver escalates
    the cap from the tightest that forces diversification (ceil(N/2)) upward and
    takes the first feasible plan; if no cap is feasible (a genuinely
    single-source BOM where every line is offered by one hub) it falls back to
    the unconstrained blind plan.
    """
    if not bom:
        raise ValueError("BOM is empty — cannot solve sourcing with zero components")

    # Pre-filter outliers
    offers, drops = filter_price_outliers(offers, bom)

    # Pre-filter by us_only
    if us_only:
        offers = [o for o in offers if o.is_domestic]

    # Collapse duplicate (component_id, distributor_id) rows to one offer.
    #
    # The offer table carries one row per price-break tier, so the same
    # (component, distributor) pair can appear up to 6 times. The CP-SAT model
    # below keys its x/q variables on (component_id, distributor_id): duplicate
    # rows silently overwrite each other's variable, but every duplicate is still
    # summed into the demand constraint and priced into the objective. That made
    # the demand constraint read k*q == demand (spuriously INFEASIBLE unless
    # demand % k == 0) and charged the unit price as the SUM of the k tier prices
    # -- STM32F103C8T6 at Verical was costed at $30.03/unit instead of $2.86, so
    # the solver systematically avoided multi-tier distributors.
    #
    # We keep the cheapest tier, which is what solve_sourcing_greedy already does
    # implicitly via min(feasible, key=price). Ties break toward more stock. This
    # under-states availability when a pricier tier holds more stock -- a
    # conservative direction, and preferable to modelling a price the distributor
    # does not charge. Proper quantity-dependent price breaks are a separate,
    # larger change.
    deduped: Dict[tuple, Offer] = {}
    for o in offers:
        key = (o.component_id, o.distributor_id)
        best = deduped.get(key)
        if best is None or (o.price_usd, -o.stock) < (best.price_usd, -best.stock):
            deduped[key] = o
    offers = list(deduped.values())

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

    all_distributors = {o.distributor_id for o in offers}

    # ── Cap-independent inputs — computed ONCE and captured by _build_and_solve.
    # These do not depend on the diversification cap, so we avoid recomputing
    # them (and re-hitting ML/graph/feed state) on every escalation iteration.
    penalty_scale = getattr(weights, "transport_penalty_scale", 1.0)
    freight = _freight_model_by_did(offers, penalty_scale)
    consolidation_bonus = getattr(weights, "consolidation_bonus_usd", 1.0)

    # Stock-out risk premium from macro stress model.
    # Falls back to 0 if ML state not loaded (no penalty applied).
    from app.ml import get_ml_state  # local import to avoid circular dep at module load
    _ml = get_ml_state()
    macro_stress = _ml.current_stress_prob if _ml is not None else 0.0

    # Graph state (graph_aware mode only); feed cache (live macro signals).
    _gs = None
    if graph_aware:
        from app.graph import get_graph_state  # local import
        _gs = get_graph_state()
    from app.feeds import get_live_data_cache  # local import to avoid circular dep
    _ldc = get_live_data_cache()

    def _build_and_solve(max_lines_cap: Optional[int]):
        """
        Build the full sourcing MILP and solve it. When ``max_lines_cap`` is
        None the model is byte-identical in behavior to the original (no
        diversification constraint). When it is an int, each distributor is
        capped to source at most that many BOM lines, forcing the plan to
        spread across multiple distributors.

        Returns (status, solver, x, q, y).
        """
        model = cp_model.CpModel()

        # x[cid, did] ∈ {0,1} — select this offer
        # q[cid, did] ∈ [0, stock] — quantity ordered
        # y[did] ∈ {0,1} — visit this distributor
        x: Dict[Tuple[int, int], cp_model.IntVar] = {}
        q: Dict[Tuple[int, int], cp_model.IntVar] = {}
        y: Dict[int, cp_model.IntVar] = {}

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

        # ── Diversification constraint (require_dual_source escalation only) ──
        # Cap how many BOM lines any single distributor may source, forcing the
        # plan to spread across ≥2 distributors instead of consolidating the
        # whole BOM onto one cheapest hub (fixed-charge economics).
        if max_lines_cap is not None:
            for did in all_distributors:
                lines_on_did = [
                    x[(b.component_id, did)]
                    for b in bom
                    if (b.component_id, did) in x
                ]
                if lines_on_did:
                    model.Add(sum(lines_on_did) <= max_lines_cap)

        # Objective: minimize total component cost + freight + consolidation charge.
        # Built in integer milli-cents (OBJ_SCALE = PRICE_SCALE x OBJ_SUBSCALE);
        # every term shares that scale, so the argmin is unchanged.
        #
        # Freight is a genuine FIXED-CHARGE model (Balinski 1965 / Kuehn & Hamburger
        # 1963), decomposed by _freight_model_by_did:
        #   fixed[d]    x y[d]              — pay once to open distributor d
        #   per_unit[d] x sum_c q[c,d]      — pay per unit d ACTUALLY ships
        # The second term is what makes splitting a BOM across suppliers divide one
        # BOM's variable freight among them, instead of charging a full BOM's
        # freight to each of them (the old bug).
        #
        # penalty_scale (from StrategyWeights.transport_penalty_scale) is already
        # baked into both components by _freight_model_by_did.
        cost_terms = []
        for b in bom:
            for o in offers_by_component[b.component_id]:
                key = (b.component_id, o.distributor_id)
                price_cents = int(round(o.price_usd * PRICE_SCALE))
                cost_terms.append(price_cents * OBJ_SUBSCALE * q[key])

        transport_terms = []
        for did in all_distributors:
            fixed_units = int(round(freight.fixed_by_did[did] * OBJ_SCALE))
            if fixed_units:
                transport_terms.append(fixed_units * y[did])

            per_unit_usd = freight.per_unit_by_did[did]
            rate_units = int(round(per_unit_usd * OBJ_SCALE))
            if rate_units == 0 and per_unit_usd > 0.0:
                # Loud rather than silent: the per-unit rate is real but below the
                # objective's milli-cent resolution (needs < $1e-5/unit, i.e. a
                # domestic distributor ~0.03 km from the depot). Dropping it is
                # numerically harmless but must never happen quietly.
                logger.warning(
                    "freight per-unit rate for distributor %s (%.3e USD/unit) rounds "
                    "to 0 at OBJ_SCALE=%d — variable freight term dropped for this "
                    "distributor",
                    did, per_unit_usd, OBJ_SCALE,
                )
            if rate_units:
                for b in bom:
                    key = (b.component_id, did)
                    if key in q:
                        transport_terms.append(rate_units * q[key])

        consolidation_terms = [
            int(round(consolidation_bonus * PRICE_SCALE)) * OBJ_SUBSCALE * y[did]
            for did in all_distributors
        ]

        # ── Risk surcharge terms ─────────────────────────────────────────────
        risk_terms = []
        for b in bom:
            for o in offers_by_component[b.component_id]:
                key = (b.component_id, o.distributor_id)
                premium = _stockout_risk_premium_cents(o, b, macro_stress)
                if premium > 0:
                    risk_terms.append(premium * OBJ_SUBSCALE * x[key])

        # ── Graph surcharge terms (graph_aware mode only) ────────────────────
        # Additive node-weight surcharge on q[key] (betweenness concentration risk)
        # plus single-source component risk. Falls back silently to zero
        # surcharge if GraphState not loaded.
        graph_surcharge_terms = []
        if graph_aware and _gs is not None:
            for b in bom:
                component_offers = offers_by_component[b.component_id]
                for o in component_offers:
                    key = (b.component_id, o.distributor_id)
                    btwn = _gs.betweenness.get(o.distributor_id, 0.0)
                    surcharge = _graph_surcharge_cents(o, btwn, component_offers)
                    if surcharge > 0:
                        graph_surcharge_terms.append(surcharge * OBJ_SUBSCALE * q[key])

        # ── Feed risk surcharge terms (live macro signals) ───────────────────
        # Additive surcharge from GPR + ACLED live feeds. Per D-01.
        # Falls back to 0 when LiveDataCache not loaded or feeds unavailable.
        feed_surcharge_terms = []
        if _ldc is not None:
            for b in bom:
                for o in offers_by_component[b.component_id]:
                    key = (b.component_id, o.distributor_id)
                    f_surcharge = _feed_risk_cents(
                        o,
                        distributor_country=getattr(o, 'distributor_country', 'US'),
                        is_chinese_origin=getattr(o, 'is_chinese_origin', False),
                        cache=_ldc,
                    )
                    if f_surcharge > 0:
                        feed_surcharge_terms.append(f_surcharge * OBJ_SUBSCALE * q[key])

        model.Minimize(
            sum(cost_terms)
            + sum(transport_terms)
            + sum(consolidation_terms)
            + sum(risk_terms)
            + sum(graph_surcharge_terms)
            + sum(feed_surcharge_terms)
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        # Single worker: these models are tiny (solve in ~ms), and a single
        # deterministic worker keeps results reproducible (seed=42 narrative)
        # and avoids an OR-Tools multi-worker deadlock seen under bare-python
        # invocation on macOS.
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)
        return status, solver, x, q, y

    # ── Solve blind first, then diversify ONLY if consolidated onto one hub ──
    # Policy: "mandate a second source for BOMs the cost-optimizer consolidated
    # onto a single hub." We never reshuffle an already-diversified plan —
    # that can only make its concentration WORSE, never better.
    status, solver, x, q, y = _build_and_solve(None)

    if require_dual_source and len(bom) >= 2 and status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        blind_dids = {
            did for (cid, did), qv in q.items() if solver.Value(qv) > 0
        }
        if len(blind_dids) == 1:
            # Blind plan puts the whole BOM on ONE hub — force a second source.
            # Escalate the cap from the tightest that forces spreading
            # (ceil(N/2)) up to N-1; take the FIRST feasible plan. A cap of N
            # would not force any diversification, so we stop below it. If NO
            # cap is feasible (genuinely single-source BOM), keep the blind plan.
            n = len(bom)
            for cap in range(math.ceil(n / 2), n):
                d_status, d_solver, d_x, d_q, d_y = _build_and_solve(cap)
                if d_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    status, solver, x, q, y = d_status, d_solver, d_x, d_q, d_y
                    break
        # else: already diversified — keep the blind result exactly as-is.

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
        objective_usd=solver.ObjectiveValue() / OBJ_SCALE,
    )
