"""
Cost-vs-CVaR efficient frontier API.

Two endpoints over `app/optimization/stochastic.py`'s two-stage stochastic program:

  POST /stochastic/frontier      Sweep the risk-aversion weight lambda for a BOM and
                                 return the (E[cost], CVaR_95[cost]) frontier, its
                                 knee, and the recommendation the knee implies.
  GET  /stochastic/calibration   The disruption probabilities themselves, per
                                 distributor, side by side with the raw betweenness
                                 they were derived from.

WHY THE CALIBRATION ENDPOINT EXISTS
-----------------------------------
The disruption probabilities are the weakest input in this whole subsystem: a cited
FIRM-level base rate reinterpreted per supplier, converted to an exposure window, and
re-shaped by a centrality rank transform. Every step is an assumption. Burying that
behind a single confident CVaR number would repeat exactly the mistake this work
exists to fix -- `graph/simulation.py` reads min-max normalized betweenness directly
as a failure probability, so its most central distributor fails in 100% of scenarios
and its `cvar_95` pins at a constant 1.15.

So the assumptions are a first-class, inspectable part of the API: `/calibration`
publishes every probability with its provenance, and `/frontier` lets the caller vary
`base_annual_prob`, `centrality_spread` and `horizon_days` and watch the knee move.
`centrality_spread = 1.0` disables centrality entirely and puts every supplier on the
flat base rate -- the "centrality tells us nothing about failure" arm.

DoS POSTURE (mirrors the T-02-03 mitigation in graph/simulation.py)
-------------------------------------------------------------------
This is a genuinely expensive endpoint -- a lambda sweep is one CP-SAT solve per point
over a scenario-expanded model. Every knob that drives cost is fixed server-side or
hard-capped: the Monte Carlo draw count and the lambda grid are NOT caller-controlled,
BOM size and per-line quantity are capped, the per-solve CP-SAT budget is small, and
results are cached for an hour on a deterministic key. The parameters a caller CAN set
(base rate, spread, horizon) change the answer but not the amount of work.

Public, no auth -- consistent with `app/api/resilience.py`, which likewise returns
aggregate cost and risk metrics derived from the catalogue and no user data.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.cache import CacheManager
from app.core.database import get_db
from app.graph import get_graph_state
from app.graph.builder import build_graph_state
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.optimization import stochastic as stoch
from app.optimization.costs import haversine_km
from app.optimization.sourcing import BomLine, Offer
from app.optimization.strategies import get_strategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stochastic", tags=["stochastic"])

# ── Server-fixed compute budget (never caller-controlled) ────────────────────
MAX_BOM_LINES = 25
MAX_LINE_QUANTITY = 100_000
N_DRAWS = 200
SEED = 42
LAMBDA_GRID: List[float] = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
SOLVE_TIME_LIMIT_S = 5.0
CACHE_SCENARIO_TYPE = "cvar-frontier"

# Depot for freight distance. Same continental reference hub the resilience API uses
# (FedEx Memphis "WorldHub"), so freight distances are comparable across endpoints.
DEPOT_LAT, DEPOT_LNG = 35.1495, -90.0490

DEFAULT_STRATEGY = "balanced"


# ── Request / response models ────────────────────────────────────────────────

class BomItem(BaseModel):
    component_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1, le=MAX_LINE_QUANTITY)


class FrontierRequest(BaseModel):
    items: List[BomItem] = Field(..., min_length=1, max_length=MAX_BOM_LINES)
    base_annual_prob: float = Field(
        stoch.DEFAULT_BASE_ANNUAL_PROB, gt=0.0, lt=1.0,
        description="Annual probability that a given supplier suffers a material "
                    "outage. Default 0.2368 = 1 - exp(-1/3.7), from McKinsey Global "
                    "Institute 2020 ('disruptions lasting a month or longer every 3.7 "
                    "years'). That is a FIRM-level frequency used here per supplier, "
                    "which likely overstates individual supplier risk -- vary it.",
    )
    horizon_days: int = Field(
        stoch.DEFAULT_HORIZON_DAYS, ge=1, le=365,
        description="Exposure window for one purchase order. The annual rate is "
                    "converted by 1 - (1 - p)**(days/365).",
    )
    centrality_spread: float = Field(
        stoch.DEFAULT_CENTRALITY_SPREAD, ge=1.0, le=10.0,
        description="How far betweenness rank is allowed to move a supplier's "
                    "probability around the base rate. The most central supplier gets "
                    "spread x the base rate, the least central 1/spread x, the median "
                    "exactly the base rate. 1.0 disables centrality entirely.",
    )
    us_only: bool = Field(False, description="Restrict to domestic distributors.")
    strategy: str = Field(DEFAULT_STRATEGY, description="Strategy weight profile id.")


class FrontierPointOut(BaseModel):
    lambda_: float = Field(..., alias="lambda")
    expected_cost_usd: float
    cvar_95_usd: float
    var_95_usd: float
    tail_premium_usd: float
    first_stage_cost_usd: float
    expected_recourse_usd: float
    n_suppliers: int
    supplier_ids: List[int]
    solver_status: str
    mip_gap_pct: float
    solve_seconds: float
    n_variables: int
    dominated: bool

    model_config = {"populate_by_name": True}


class DistributorRisk(BaseModel):
    distributor_id: int
    distributor_name: str
    betweenness_normalized: float
    p_disruption_over_horizon: float
    legacy_simulator_p_fail: float = Field(
        ...,
        description="What graph/simulation.py would use for this distributor: the "
                    "min-max normalized betweenness itself. Published alongside so the "
                    "difference is auditable rather than asserted.",
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _graph(db: Session):
    """Live GraphState, built on demand when the app lifespan has not run (tests)."""
    gs = get_graph_state()
    if gs is None:
        gs = build_graph_state(db)
    return gs


# The ORM models in app/models/* use SQLAlchemy's legacy `Column(...)` declarative
# style with no `Mapped[...]` annotations, so the mypy plugin infers every column as
# nullable even for NOT NULL primary keys and coordinates. These two helpers narrow at
# the boundary AND add a real guard: a NULL id or coordinate would otherwise surface as
# a TypeError deep inside the freight model, which is a much worse failure than a clear
# 500 raised here naming the field.
def _req_int(value: Optional[int], field: str) -> int:
    if value is None:
        raise HTTPException(status_code=500, detail=f"{field} is unexpectedly NULL")
    return int(value)


def _req_float(value: Any, field: str) -> float:
    # `Any` rather than `Optional[float]`: SQLAlchemy types numeric columns with an
    # internal TypeVar (`_N | None`) that no concrete annotation matches. The runtime
    # narrowing below is real, and the return type is concrete, so nothing downstream
    # loses type information.
    if value is None:
        raise HTTPException(status_code=500, detail=f"{field} is unexpectedly NULL")
    return float(value)


def _load_bom_and_offers(
    db: Session, items: List[BomItem],
) -> tuple[List[BomLine], List[Offer]]:
    """Resolve component ids to a BOM and the full offer pool, as optimize.py does."""
    comp_ids = [i.component_id for i in items]
    components: Dict[int, Component] = {
        _req_int(c.id, "component.id"): c
        for c in db.query(Component).filter(Component.id.in_(comp_ids)).all()
    }

    bom: List[BomLine] = []
    for item in items:
        comp = components.get(item.component_id)
        if comp is None:
            raise HTTPException(
                status_code=404,
                detail=f"component_id {item.component_id} not found",
            )
        bom.append(BomLine(
            component_id=_req_int(comp.id, "component.id"),
            mpn=str(comp.mpn),
            quantity=int(item.quantity),
            category=str(comp.category) if comp.category is not None else None,
        ))

    offer_rows = db.query(DistributorOffer).filter(
        DistributorOffer.component_id.in_(comp_ids)
    ).all()
    dist_ids = {_req_int(o.distributor_id, "offer.distributor_id") for o in offer_rows}
    dist_by_id: Dict[int, Distributor] = {
        _req_int(d.id, "distributor.id"): d
        for d in (
            db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
            if dist_ids else []
        )
    }

    offers: List[Offer] = []
    for row in offer_rows:
        dist = dist_by_id.get(_req_int(row.distributor_id, "offer.distributor_id"))
        price = row.price
        if dist is None or price is None or float(price) <= 0:
            continue
        comp = components.get(_req_int(row.component_id, "offer.component_id"))
        risk_factors = (comp.risk_factors if comp is not None else None) or []
        is_chinese = any("chinese" in str(f).lower() for f in risk_factors)
        offers.append(Offer(
            component_id=_req_int(row.component_id, "offer.component_id"),
            distributor_id=_req_int(row.distributor_id, "offer.distributor_id"),
            distributor_name=str(dist.name),
            price_usd=float(price),
            stock=int(row.stock or 0),
            moq=int(row.moq or 1),
            is_domestic=bool(dist.is_domestic),
            dist_km_from_depot=haversine_km(
                DEPOT_LAT, DEPOT_LNG,
                _req_float(dist.latitude, "distributor.latitude"),
                _req_float(dist.longitude, "distributor.longitude"),
            ),
            risk_score=float(comp.risk_score) if comp is not None and comp.risk_score is not None else 0.5,
            is_chinese_origin=is_chinese,
            distributor_country=str(dist.country or "US"),
        ))

    return bom, offers


def _point_out(p: stoch.FrontierPoint) -> Dict[str, Any]:
    return {
        "lambda": round(p.lam, 4),
        "expected_cost_usd": round(p.expected_cost_usd, 2),
        "cvar_95_usd": round(p.cvar_usd, 2),
        "var_95_usd": round(p.var_usd, 2),
        "tail_premium_usd": round(p.cvar_usd - p.expected_cost_usd, 2),
        "first_stage_cost_usd": round(p.first_stage_cost_usd, 2),
        "expected_recourse_usd": round(p.expected_recourse_usd, 2),
        "n_suppliers": p.n_suppliers,
        "supplier_ids": p.supplier_ids,
        "solver_status": p.status,
        "mip_gap_pct": round(p.gap_pct, 4),
        "solve_seconds": round(p.wall_seconds, 3),
        "n_variables": p.n_variables,
        "dominated": p.dominated,
    }


def _recommendation(points: List[stoch.FrontierPoint]) -> Optional[Dict[str, Any]]:
    """
    The knee, expressed as the decision it implies rather than as a coordinate.

    The two ratios are the whole point: how many dollars of tail exposure one extra
    dollar of expected cost removes BEFORE the knee, and how few it removes after.
    That contrast is the recommendation.
    """
    knee = stoch.find_knee(points)
    if knee is None:
        return None
    usable = sorted(
        [p for p in points if not p.dominated], key=lambda p: p.expected_cost_usd,
    )
    lo, hi = usable[0], usable[-1]

    d_e = knee.expected_cost_usd - lo.expected_cost_usd
    d_c = lo.cvar_usd - knee.cvar_usd
    d_e_after = hi.expected_cost_usd - knee.expected_cost_usd
    d_c_after = knee.cvar_usd - hi.cvar_usd

    return {
        "knee_lambda": round(knee.lam, 4),
        "expected_cost_usd": round(knee.expected_cost_usd, 2),
        "cvar_95_usd": round(knee.cvar_usd, 2),
        "n_suppliers": knee.n_suppliers,
        "supplier_ids": knee.supplier_ids,
        "extra_expected_cost_usd": round(d_e, 2),
        "extra_expected_cost_pct": round(100.0 * d_e / lo.expected_cost_usd, 4)
        if lo.expected_cost_usd else 0.0,
        "cvar_reduction_usd": round(d_c, 2),
        "cvar_reduction_pct": round(100.0 * d_c / lo.cvar_usd, 4) if lo.cvar_usd else 0.0,
        "cvar_removed_per_dollar_spent": round(d_c / d_e, 3) if d_e > 1e-9 else None,
        "cvar_removed_per_dollar_spent_beyond_knee": round(d_c_after / d_e_after, 3)
        if d_e_after > 1e-9 else None,
        "statement": (
            f"Moving from the risk-neutral plan to lambda={knee.lam:g} costs "
            f"${d_e:,.0f} more in expectation and removes ${d_c:,.0f} of CVaR-95 "
            f"exposure. Past that point the trade stops paying."
        ),
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/frontier")
def compute_cvar_frontier(
    body: FrontierRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Sweep lambda in `min (1-lambda)*E[cost] + lambda*CVaR_95[cost]` and return the
    cost-vs-tail-risk efficient frontier, its knee, and the implied recommendation.

    The frontier replaces the flat risk surcharge `app/optimization/sourcing.py`
    applies today (`RISK_PREMIUM_RATE = 0.15` times a hand-weighted vulnerability
    score). Instead of one hard-coded risk appetite, the caller sees the whole
    price-of-resilience curve and where it stops being worth paying for.

    Caveats returned in the response, not buried here: the lambda grid is a weighted-sum
    scalarization and can only recover Pareto points on the convex hull of the
    (E, CVaR) image; and the disruption probabilities are an assumption whose
    parameters are exposed on this request precisely so they can be flexed.
    """
    try:
        weights = get_strategy(body.strategy)
    except KeyError:
        raise HTTPException(
            status_code=400, detail=f"Unknown strategy: {body.strategy}",
        ) from None

    cache_key = CacheManager.generate_key(CACHE_SCENARIO_TYPE, {
        "items": sorted((i.component_id, i.quantity) for i in body.items),
        "base_annual_prob": round(body.base_annual_prob, 6),
        "horizon_days": body.horizon_days,
        "centrality_spread": body.centrality_spread,
        "us_only": body.us_only,
        "strategy": body.strategy,
        "n_draws": N_DRAWS,
        "seed": SEED,
        "lambda_grid": LAMBDA_GRID,
    })
    try:
        cached = CacheManager.get(db, cache_key)
    except Exception as exc:  # noqa: BLE001 - a cache miss must never fail the request
        logger.warning("cvar-frontier cache get failed: %s", exc)
        cached = None
    if cached is not None:
        cached["cached"] = True
        return cached

    bom, offers = _load_bom_and_offers(db, body.items)
    if not offers:
        raise HTTPException(
            status_code=422,
            detail="No priced offers exist for the requested components",
        )

    gs = _graph(db)
    pool = sorted({o.distributor_id for o in offers})
    probs = stoch.build_failure_probabilities(
        pool,
        gs.betweenness,
        base_annual_prob=body.base_annual_prob,
        horizon_days=body.horizon_days,
        centrality_spread=body.centrality_spread,
    )
    scenarios = stoch.sample_scenarios(probs, n_draws=N_DRAWS, seed=SEED)

    t0 = time.perf_counter()
    try:
        points, _results = stoch.compute_frontier(
            bom, offers, weights, scenarios, LAMBDA_GRID,
            alpha=stoch.DEFAULT_ALPHA, us_only=body.us_only,
            time_limit_s=SOLVE_TIME_LIMIT_S,
        )
    except ValueError as exc:
        # Infeasible input (no offers after filtering, empty BOM, bad alpha) is a
        # client-side problem; report it as one rather than a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"No feasible sourcing plan exists for this BOM: {exc}",
        ) from exc
    wall = time.perf_counter() - t0

    result: Dict[str, Any] = {
        "cached": False,
        "frontier": [_point_out(p) for p in points],
        "recommendation": _recommendation(points),
        "calibration": {
            "base_annual_prob": round(body.base_annual_prob, 6),
            "horizon_days": body.horizon_days,
            "centrality_spread": body.centrality_spread,
            "p_disruption_min": round(min(probs.values()), 5) if probs else 0.0,
            "p_disruption_median": round(
                sorted(probs.values())[len(probs) // 2], 5) if probs else 0.0,
            "p_disruption_max": round(max(probs.values()), 5) if probs else 0.0,
            "n_distributors_in_pool": len(pool),
        },
        "scenarios": {
            "n_draws": scenarios.n_draws,
            "n_distinct": scenarios.n_distinct,
            "seed": scenarios.seed,
            "p_no_disruption": round(scenarios.p_no_disruption, 4),
            "mean_failures_per_scenario": round(scenarios.mean_failures_per_scenario, 4),
        },
        "solver": {
            "engine": "OR-Tools CP-SAT",
            "num_search_workers": 1,
            "max_time_in_seconds_per_point": SOLVE_TIME_LIMIT_S,
            "sweep_wall_seconds": round(wall, 3),
            "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
            "any_point_hit_time_limit": any(p.status != "OPTIMAL" for p in points),
        },
        "caveats": [
            "The disruption probabilities are an ASSUMPTION, not a measurement. The "
            "base rate is a firm-level frequency (McKinsey Global Institute 2020) used "
            "here per supplier, which likely overstates individual supplier risk. Vary "
            "base_annual_prob, horizon_days and centrality_spread and re-read the knee.",
            "centrality_spread=1.0 removes centrality from the model entirely and puts "
            "every supplier on the flat base rate. If the recommendation changes a lot "
            "between spread=1 and spread=3, it is being driven by the centrality "
            "assumption rather than by the cost data.",
            "A lambda sweep is a weighted-sum scalarization: it recovers only Pareto "
            "points on the convex hull of the (E, CVaR) image, so this frontier is a "
            "subset of the true efficient set, never a superset.",
            "Supplier failures are drawn independently. Real disruptions are "
            "correlated, so the tail reported here is if anything optimistic.",
            "Expected cost and CVaR are computed by re-solving each scenario's second "
            "stage exactly for the returned plan, so they describe the plan even when a "
            "point did not close its MIP gap. Check solver.any_point_hit_time_limit.",
        ],
    }

    try:
        CacheManager.set(db, cache_key, CACHE_SCENARIO_TYPE, result)
    except Exception as exc:  # noqa: BLE001 - caching is best-effort
        logger.warning("cvar-frontier cache set failed: %s", exc)

    return result


@router.get("/calibration")
def get_disruption_calibration(
    base_annual_prob: float = stoch.DEFAULT_BASE_ANNUAL_PROB,
    horizon_days: int = stoch.DEFAULT_HORIZON_DAYS,
    centrality_spread: float = stoch.DEFAULT_CENTRALITY_SPREAD,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Every disruption probability the stochastic program uses, with its provenance --
    and, next to each one, what `graph/simulation.py` would have used instead.

    This endpoint exists to make the weakest assumption in the subsystem the easiest
    thing to inspect. The `legacy_simulator_p_fail` column is the min-max normalized
    betweenness that `graph/simulation.py:155-161` feeds straight into a Bernoulli
    draw: it reaches exactly 1.0 for the most central distributor in the network, which
    is why that simulator's `cvar_95` saturates at 1.15 in nearly every published
    benchmark row. Nothing here modifies that module; this is the replacement, shown
    beside it.
    """
    if not 0.0 < base_annual_prob < 1.0:
        raise HTTPException(status_code=400, detail="base_annual_prob must be in (0, 1)")
    if not 1 <= horizon_days <= 365:
        raise HTTPException(status_code=400, detail="horizon_days must be in [1, 365]")
    if not 1.0 <= centrality_spread <= 10.0:
        raise HTTPException(status_code=400, detail="centrality_spread must be in [1, 10]")

    gs = _graph(db)
    dist_ids = sorted(gs.betweenness)
    names: Dict[int, str] = {
        _req_int(d.id, "distributor.id"): str(d.name)
        for d in db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
    }
    probs = stoch.build_failure_probabilities(
        dist_ids, gs.betweenness,
        base_annual_prob=base_annual_prob,
        horizon_days=horizon_days,
        centrality_spread=centrality_spread,
    )
    legacy_max = max(gs.betweenness.values()) if gs.betweenness else 0.0

    return {
        "method": (
            "p_d = min(base_horizon_prob * spread**(2*rank_d - 1), max_failure_prob), "
            "where rank_d is the percentile rank of distributor d's betweenness (ties "
            "share the mean rank) and base_horizon_prob = "
            "1 - (1 - base_annual_prob)**(horizon_days/365)."
        ),
        "parameters": {
            "base_annual_prob": round(base_annual_prob, 6),
            "horizon_days": horizon_days,
            "centrality_spread": centrality_spread,
            "base_horizon_prob": round(
                stoch.annual_to_horizon_prob(base_annual_prob, horizon_days), 6),
            "max_failure_prob": stoch.MAX_FAILURE_PROB,
        },
        "base_rate_source": {
            "citation": "McKinsey Global Institute, 'Risk, resilience, and rebalancing "
                        "in global value chains', August 2020",
            "quote": "companies can now expect supply chain disruptions lasting a month "
                     "or longer to occur every 3.7 years",
            "derivation": "Poisson rate 1/3.7 per year -> 1 - exp(-1/3.7) = 0.2368",
            "known_weakness": "Firm-level, not per-supplier. Used per supplier here, "
                              "which likely overstates individual supplier risk. Treat "
                              "as an assumption and vary it.",
        },
        "contrast_with_existing_simulator": {
            "what_it_does": "graph/simulation.py:155-161 uses min-max normalized "
                            "betweenness DIRECTLY as p_fail.",
            "why_that_breaks": "A min-max normalization attains 1.0 at its maximum, so "
                               "the most central distributor fails in 100% of scenarios "
                               "and distributors at betweenness 0.0 never fail. There is "
                               "no base rate, no exposure window and no unit in that "
                               "expression.",
            "max_legacy_p_fail": round(legacy_max, 6),
            "max_calibrated_p_fail": round(max(probs.values()), 6) if probs else 0.0,
            "note": "graph/simulation.py is deliberately left unchanged; other published "
                    "documents depend on its numbers. This is the replacement used by "
                    "the stochastic program, published beside it.",
        },
        "distributors": [
            DistributorRisk(
                distributor_id=did,
                distributor_name=names.get(did, f"distributor-{did}"),
                betweenness_normalized=round(gs.betweenness.get(did, 0.0), 6),
                p_disruption_over_horizon=round(probs[did], 6),
                legacy_simulator_p_fail=round(gs.betweenness.get(did, 0.0), 6),
            ).model_dump()
            for did in dist_ids
        ],
    }
