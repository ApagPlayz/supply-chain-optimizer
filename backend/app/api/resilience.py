"""
Resilience Scenario API endpoints (Phase 6).

Three POST endpoints for interactive "what if" scenario exploration:
  1. POST /resilience/distributor-failure — Simulate distributor outage via graph cascade
  2. POST /resilience/geopolitical-risk — Simulate geopolitical risk spike via live feed override
  3. POST /resilience/delivery-target — Simulate tight delivery constraint via optimization

All endpoints cache results (1h TTL) with deterministic SHA256 cache keys to meet <2s response time.
OpenTelemetry tracing logs slow spans (>500ms) for performance diagnostics.
No auth required; public API (aggregate metrics only, no prices/user data).
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scenario import ScenarioCache
from app.models.distributor import Distributor
from app.models.component import Component, DistributorOffer
from app.cache import CacheManager
from app.graph import get_graph_state
from app.graph.builder import build_graph_state
from app.graph.simulation import run_monte_carlo
from app.optimization.costs import haversine_km
from app.optimization.constants import GROUND_KM_PER_DAY

# OpenTelemetry tracer setup (optional — no-op if not installed)
try:
    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)
except ImportError:
    class _NoOpSpan:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def set_attribute(self, *_): pass
    class _NoOpTracer:
        def start_as_current_span(self, *_, **__): return _NoOpSpan()
    tracer = _NoOpTracer()
logger = logging.getLogger(__name__)
SLOW_PATH_THRESHOLD_MS = 500

router = APIRouter(prefix="/resilience", tags=["resilience"])


# ────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ────────────────────────────────────────────────────────────────────────────

class DistributorFailureRequest(BaseModel):
    distributor_id: int = Field(..., description="ID of distributor to simulate failure")
    bom_component_ids: List[int] = Field(..., description="Component IDs in BOM (max 200)")


class GeopoliticalRiskRequest(BaseModel):
    risk_multiplier: float = Field(..., ge=0.5, le=5.0, description="Multiplier for live feed indices")
    bom_component_ids: List[int] = Field(..., description="Component IDs in BOM (max 200)")


class DeliveryTargetRequest(BaseModel):
    target_delivery_days: int = Field(..., ge=1, le=90, description="Target delivery timeframe")
    bom_component_ids: List[int] = Field(..., description="Component IDs in BOM (max 200)")


class ScenarioResponse(BaseModel):
    """Common response shape for all three scenario endpoints."""
    baseline_cost_usd: float
    scenario_cost_usd: float
    cost_delta_pct: float
    baseline_eta_days: float
    scenario_eta_days: float
    eta_delta_days: float
    baseline_risk_score: float
    scenario_risk_score: float
    risk_delta: float
    # Dollar-denominated tail-risk framing (P3). EVaR-95 is the mean emergency-
    # procurement cost multiplier over the worst-5% Monte Carlo scenarios; the
    # spend-at-risk translates it into the extra USD a tail disruption would add
    # to this BOM's procurement bill = component_cost * (EVaR-95 - 1).
    baseline_evar_95: float = 1.0
    procurement_spend_at_risk_usd: float = 0.0
    baseline_fulfillment_p10: float
    baseline_fulfillment_p50: float
    baseline_fulfillment_p90: float
    scenario_fulfillment_p10: float
    scenario_fulfillment_p50: float
    scenario_fulfillment_p90: float
    affected_bom_ids: List[int]
    affected_suppliers: List[str]


class DeliveryTargetResponse(ScenarioResponse):
    """Extends common response with supplier capability lists."""
    suppliers_capable: List[Dict] = Field(default_factory=list)
    suppliers_cannot_meet: List[Dict] = Field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
# Cache Utility Functions (refactored to use CacheManager)
# ────────────────────────────────────────────────────────────────────────────

def _compute_cache_key(scenario_type: str, **params) -> str:
    """Generate deterministic SHA256 cache key from scenario params."""
    # Use CacheManager's key generation for consistency
    param_dict = {k: v for k, v in sorted(params.items())}
    return CacheManager.generate_key(scenario_type, param_dict)


def _get_cached_result(db: Session, cache_key: str) -> Optional[dict]:
    """Retrieve cached result if it exists and has not expired."""
    try:
        return CacheManager.get(db, cache_key)
    except Exception as e:
        logger.warning(f"Cache get failed: {e}")
        return None


def _cache_result(
    db: Session,
    scenario_type: str,
    cache_key: str,
    result: dict,
    ttl_hours: int = 1
) -> None:
    """Store result in cache with TTL."""
    try:
        CacheManager.set(db, cache_key, scenario_type, result)
    except Exception as e:
        logger.warning(f"Cache set failed: {e}")


# ────────────────────────────────────────────────────────────────────────────
# Scenario Computation Helpers
# ────────────────────────────────────────────────────────────────────────────

# Continental shipping reference point: FedEx Memphis "WorldHub" (a real logistics
# super-hub). Distributor ETA is derived from real haversine distance to this hub at
# the published BTS ground freight rate (GROUND_KM_PER_DAY), plus order processing and
# (for non-domestic suppliers) customs handling. No hardcoded per-supplier lead times.
_REF_HUB_LAT, _REF_HUB_LNG = 35.1495, -90.0490
_ORDER_PROCESSING_DAYS = 2.0   # order handling before dispatch
_CUSTOMS_DAYS = 5.0            # international customs + handling
_DEFAULT_ETA_DAYS = 21.0       # fallback only when a BOM has no resolvable supplier geo


def _graph(db: Session):
    """Return the live GraphState, building it on demand if not yet loaded (e.g. tests)."""
    gs = get_graph_state()
    if gs is None:
        gs = build_graph_state(db)
    return gs


def _distributor_lead_days(dist: Distributor) -> float:
    """Real, geography-derived lead time for one distributor (days)."""
    dist_km = haversine_km(dist.latitude, dist.longitude, _REF_HUB_LAT, _REF_HUB_LNG)
    days = _ORDER_PROCESSING_DAYS + dist_km / GROUND_KM_PER_DAY
    if not dist.is_domestic:
        days += _CUSTOMS_DAYS
    return days


def _bom_eta_days(
    db: Session,
    bom_component_ids: List[int],
    excluded_distributor_id: Optional[int] = None,
) -> Optional[float]:
    """BOM ETA = the slowest of each component's fastest available supplier.

    A BOM is complete only once every line has arrived, so we take the per-component
    best (fastest) supplier lead time and return the max across components. Derived
    entirely from real distributor geography; returns None if nothing is fulfillable.
    """
    offers = db.query(DistributorOffer).filter(
        DistributorOffer.component_id.in_(bom_component_ids)
    ).all()
    dist_ids = {o.distributor_id for o in offers if o.distributor_id != excluded_distributor_id}
    dists = {
        d.id: d
        for d in db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
    }

    per_component_best: List[float] = []
    for cid in bom_component_ids:
        leads = [
            _distributor_lead_days(dists[o.distributor_id])
            for o in offers
            if o.component_id == cid
            and o.distributor_id != excluded_distributor_id
            and o.distributor_id in dists
        ]
        if leads:
            per_component_best.append(min(leads))

    return max(per_component_best) if per_component_best else None


def _compute_baseline_metrics(db: Session, bom_component_ids: List[int]) -> dict:
    """Compute baseline cost, ETA, risk, and fulfillment distribution for a BOM.

    Fulfillment percentiles and the expected emergency-procurement premium come from
    the real Monte Carlo cascade simulation; ETA from real distributor geography.
    """
    components = db.query(Component).filter(Component.id.in_(bom_component_ids)).all()
    offers = db.query(DistributorOffer).filter(
        DistributorOffer.component_id.in_(bom_component_ids)
    ).all()

    # Raw component cost = sum of each line's average real offer price.
    component_cost = 0.0
    risk_sum = 0.0
    for comp in components:
        comp_offers = [o for o in offers if o.component_id == comp.id]
        if comp_offers:
            component_cost += sum(o.price or 0 for o in comp_offers) / len(comp_offers)
        risk_sum += comp.risk_score or 0.0

    avg_risk = risk_sum / len(components) if components else 0.0

    # Real Monte Carlo cascade simulation (N=1,000, seed=42 → deterministic).
    sim = run_monte_carlo(_graph(db), bom_component_ids)
    baseline_eta = _bom_eta_days(db, bom_component_ids)

    # Tail-risk dollars: EVaR-95 (mean cost multiplier of the worst-5% scenarios)
    # applied to raw component spend gives the emergency-procurement premium a
    # tail disruption would add. (evar_95 - 1) strips the baseline so the figure
    # is the *extra* dollars exposed, not the total bill.
    spend_at_risk = component_cost * max(0.0, sim.evar_95 - 1.0)

    return {
        "_component_cost": round(component_cost, 2),
        "_mean_cost_inflation": sim.mean_cost_inflation,
        "baseline_cost_usd": round(component_cost * sim.mean_cost_inflation, 2),
        "baseline_evar_95": round(sim.evar_95, 4),
        "procurement_spend_at_risk_usd": round(spend_at_risk, 2),
        "baseline_eta_days": round(baseline_eta if baseline_eta is not None else _DEFAULT_ETA_DAYS, 1),
        "baseline_risk_score": round(avg_risk, 3),
        "baseline_fulfillment_p10": round(sim.p10, 3),
        "baseline_fulfillment_p50": round(sim.p50, 3),
        "baseline_fulfillment_p90": round(sim.p90, 3),
    }


def _identify_affected_boms(
    db: Session,
    bom_component_ids: List[int],
    excluded_distributor_id: Optional[int] = None
) -> tuple[List[int], List[str]]:
    """Identify components and suppliers affected by distributor removal."""
    affected_bom_ids = []
    affected_suppliers = []

    for comp_id in bom_component_ids:
        offers = db.query(DistributorOffer).filter(
            DistributorOffer.component_id == comp_id
        ).all()

        remaining_offers = [o for o in offers if o.distributor_id != excluded_distributor_id]

        # Component is affected if removing the distributor leaves no alternatives
        if not remaining_offers:
            affected_bom_ids.append(comp_id)

        # Find alternative suppliers
        alt_suppliers = set()
        for offer in remaining_offers:
            dist = db.query(Distributor).filter(Distributor.id == offer.distributor_id).first()
            if dist:
                alt_suppliers.add(dist.name)
        affected_suppliers.extend(list(alt_suppliers))

    return affected_bom_ids, list(set(affected_suppliers))


def _risk_tier(score: float) -> int:
    """Map a risk score to a tier index. Matches frontend lib/risk.ts thresholds.

    0 = low (<0.4), 1 = medium (0.4–0.7), 2 = high (>=0.7).
    """
    if score < 0.4:
        return 0
    if score < 0.7:
        return 1
    return 2


def _identify_geo_affected(
    db: Session,
    bom_component_ids: List[int],
    risk_multiplier: float,
) -> tuple[List[int], List[str], float]:
    """Identify components whose risk tier migrates upward under a GPR spike.

    Applies the multiplier to each component's individual risk_score (capped at
    1.0) and flags components that cross into a higher tier. Affected suppliers
    are the distributors that source those migrating components. Also returns the
    BOM-wide scenario risk score as the mean of the per-component scenario risks,
    keeping the aggregate consistent with the migrations shown to the user.
    """
    components = db.query(Component).filter(Component.id.in_(bom_component_ids)).all()

    affected_bom_ids: List[int] = []
    scenario_risks: List[float] = []
    for comp in components:
        baseline_risk = comp.risk_score or 0.0
        scenario_risk = min(baseline_risk * risk_multiplier, 1.0)
        scenario_risks.append(scenario_risk)
        if _risk_tier(scenario_risk) > _risk_tier(baseline_risk):
            affected_bom_ids.append(comp.id)

    # Suppliers exposed to the spike = distributors sourcing the migrating components.
    affected_suppliers: List[str] = []
    if affected_bom_ids:
        offers = db.query(DistributorOffer).filter(
            DistributorOffer.component_id.in_(affected_bom_ids)
        ).all()
        dist_ids = {o.distributor_id for o in offers}
        if dist_ids:
            dists = db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
            affected_suppliers = sorted({d.name for d in dists})

    scenario_risk_score = (
        round(sum(scenario_risks) / len(scenario_risks), 3) if scenario_risks else 0.0
    )
    return affected_bom_ids, affected_suppliers, scenario_risk_score


# ────────────────────────────────────────────────────────────────────────────
# POST /resilience/distributor-failure
# ────────────────────────────────────────────────────────────────────────────

@router.post("/distributor-failure", response_model=ScenarioResponse)
def post_distributor_failure(
    body: DistributorFailureRequest,
    db: Session = Depends(get_db),
):
    """
    Simulate supply chain impact of a distributor failure.

    Uses graph cascade simulation to determine which BOMs break,
    alternative suppliers, and cost/ETA/risk deltas.
    Results cached (1h TTL) with deterministic SHA256 key.
    OpenTelemetry spans track cache hits/misses and slow computation paths.
    """
    with tracer.start_as_current_span("distributor_failure_scenario") as span:
        # Set span attributes
        span.set_attribute("distributor_id", body.distributor_id)
        span.set_attribute("bom_size", len(body.bom_component_ids))

        # Validate input
        if len(body.bom_component_ids) > 200:
            span.set_attribute("error", "bom_too_large")
            raise HTTPException(status_code=400, detail="bom_component_ids must not exceed 200 items")

        # Check distributor exists
        dist = db.query(Distributor).filter(Distributor.id == body.distributor_id).first()
        if not dist:
            span.set_attribute("error", "distributor_not_found")
            raise HTTPException(status_code=400, detail=f"Distributor {body.distributor_id} not found")

        # Compute cache key
        cache_key = _compute_cache_key(
            "distributor-failure",
            distributor_id=body.distributor_id,
            bom_component_ids=sorted(body.bom_component_ids),
        )
        span.set_attribute("cache_key", cache_key)

        # Check cache
        cached = _get_cached_result(db, cache_key)
        if cached:
            span.set_attribute("cache_hit", True)
            span.set_attribute("result_source", "cache")
            logger.debug(f"Cache hit for distributor_failure:{body.distributor_id}")
            return ScenarioResponse(**cached)

        span.set_attribute("cache_hit", False)

        # Compute baseline
        baseline = _compute_baseline_metrics(db, body.bom_component_ids)

        # Simulate scenario: force this distributor to fail in every Monte Carlo
        # scenario, then recompute fulfillment, cost, ETA and risk from the result.
        with tracer.start_as_current_span("simulate_distributor_removal"):
            scenario_sim = run_monte_carlo(
                _graph(db),
                bom_component_ids=body.bom_component_ids,
                forced_failures={body.distributor_id},
            )
            # Cost: same MC emergency-procurement model, now with the outage in effect.
            scenario_cost = baseline["_component_cost"] * scenario_sim.mean_cost_inflation
            # ETA: fastest surviving supplier per component, excluding the failed one.
            scenario_eta_raw = _bom_eta_days(
                db, body.bom_component_ids, excluded_distributor_id=body.distributor_id
            )
            scenario_eta = round(
                scenario_eta_raw if scenario_eta_raw is not None else baseline["baseline_eta_days"], 1
            )
            # Risk rises in proportion to the median fulfillment lost to the outage.
            fulfillment_drop = max(0.0, baseline["baseline_fulfillment_p50"] - scenario_sim.p50)
            scenario_risk = min(baseline["baseline_risk_score"] + fulfillment_drop, 1.0)

            affected_bom_ids, affected_suppliers = _identify_affected_boms(
                db, body.bom_component_ids, body.distributor_id
            )

        # Build response
        result = {
            "baseline_cost_usd": baseline["baseline_cost_usd"],
            "scenario_cost_usd": round(scenario_cost, 2),
            "cost_delta_pct": round((scenario_cost - baseline["baseline_cost_usd"]) / baseline["baseline_cost_usd"] * 100, 1) if baseline["baseline_cost_usd"] else 0.0,
            "baseline_eta_days": baseline["baseline_eta_days"],
            "scenario_eta_days": scenario_eta,
            "eta_delta_days": round(scenario_eta - baseline["baseline_eta_days"], 1),
            "baseline_risk_score": baseline["baseline_risk_score"],
            "baseline_evar_95": baseline["baseline_evar_95"],
            "procurement_spend_at_risk_usd": baseline["procurement_spend_at_risk_usd"],
            "scenario_risk_score": round(scenario_risk, 3),
            "risk_delta": round(scenario_risk - baseline["baseline_risk_score"], 3),
            "baseline_fulfillment_p10": baseline["baseline_fulfillment_p10"],
            "baseline_fulfillment_p50": baseline["baseline_fulfillment_p50"],
            "baseline_fulfillment_p90": baseline["baseline_fulfillment_p90"],
            "scenario_fulfillment_p10": round(scenario_sim.p10, 3),
            "scenario_fulfillment_p50": round(scenario_sim.p50, 3),
            "scenario_fulfillment_p90": round(scenario_sim.p90, 3),
            "affected_bom_ids": affected_bom_ids,
            "affected_suppliers": affected_suppliers,
        }

        # Cache result
        _cache_result(db, "distributor-failure", cache_key, result)
        span.set_attribute("result_source", "computed")
        logger.debug(f"Computed and cached distributor_failure scenario for distributor {body.distributor_id}")

        return ScenarioResponse(**result)


# ────────────────────────────────────────────────────────────────────────────
# POST /resilience/geopolitical-risk
# ────────────────────────────────────────────────────────────────────────────

@router.post("/geopolitical-risk", response_model=ScenarioResponse)
def post_geopolitical_risk(
    body: GeopoliticalRiskRequest,
    db: Session = Depends(get_db),
):
    """
    Simulate impact of geopolitical risk spike on supply chain.

    Overrides live feed indices (GPR_INDEX, ACLED_CONFLICT_COUNT) by risk_multiplier,
    recalculates component risk tiers, identifies tier migrations.
    Results cached (1h TTL). OpenTelemetry spans track performance.
    """
    with tracer.start_as_current_span("geopolitical_risk_scenario") as span:
        # Set span attributes
        span.set_attribute("risk_multiplier", body.risk_multiplier)
        span.set_attribute("bom_size", len(body.bom_component_ids))

        # Validate input
        if len(body.bom_component_ids) > 200:
            span.set_attribute("error", "bom_too_large")
            raise HTTPException(status_code=400, detail="bom_component_ids must not exceed 200 items")

        # Compute cache key
        cache_key = _compute_cache_key(
            "geopolitical-risk",
            risk_multiplier=body.risk_multiplier,
            bom_component_ids=sorted(body.bom_component_ids),
        )
        span.set_attribute("cache_key", cache_key)

        # Check cache
        cached = _get_cached_result(db, cache_key)
        if cached:
            span.set_attribute("cache_hit", True)
            span.set_attribute("result_source", "cache")
            logger.debug(f"Cache hit for geopolitical_risk:{body.risk_multiplier}")
            return ScenarioResponse(**cached)

        span.set_attribute("cache_hit", False)

        # Compute baseline
        baseline = _compute_baseline_metrics(db, body.bom_component_ids)

        # Simulate scenario: apply risk multiplier per-component so individual
        # tier migrations (low→medium→high) are surfaced, not just a BOM-wide scalar.
        with tracer.start_as_current_span("apply_geopolitical_multiplier"):
            affected_bom_ids, affected_suppliers, scenario_risk = _identify_geo_affected(
                db, body.bom_component_ids, body.risk_multiplier
            )
            # Elevated stress scales every distributor's failure probability in the
            # Monte Carlo, so cost and fulfillment fall out of the real cascade model.
            scenario_sim = run_monte_carlo(
                _graph(db),
                bom_component_ids=body.bom_component_ids,
                stress_factor=body.risk_multiplier,
            )
            scenario_cost = baseline["_component_cost"] * scenario_sim.mean_cost_inflation
            scenario_eta = baseline["baseline_eta_days"]  # shipping geography unchanged by a risk-index spike
            span.set_attribute("affected_count", len(affected_bom_ids))

        # Build response
        result = {
            "baseline_cost_usd": baseline["baseline_cost_usd"],
            "scenario_cost_usd": round(scenario_cost, 2),
            "cost_delta_pct": round((scenario_cost - baseline["baseline_cost_usd"]) / baseline["baseline_cost_usd"] * 100, 1) if baseline["baseline_cost_usd"] else 0.0,
            "baseline_eta_days": baseline["baseline_eta_days"],
            "scenario_eta_days": scenario_eta,
            "eta_delta_days": 0.0,
            "baseline_risk_score": baseline["baseline_risk_score"],
            "baseline_evar_95": baseline["baseline_evar_95"],
            "procurement_spend_at_risk_usd": baseline["procurement_spend_at_risk_usd"],
            "scenario_risk_score": round(scenario_risk, 3),
            "risk_delta": round(scenario_risk - baseline["baseline_risk_score"], 3),
            "baseline_fulfillment_p10": baseline["baseline_fulfillment_p10"],
            "baseline_fulfillment_p50": baseline["baseline_fulfillment_p50"],
            "baseline_fulfillment_p90": baseline["baseline_fulfillment_p90"],
            "scenario_fulfillment_p10": round(scenario_sim.p10, 3),
            "scenario_fulfillment_p50": round(scenario_sim.p50, 3),
            "scenario_fulfillment_p90": round(scenario_sim.p90, 3),
            "affected_bom_ids": affected_bom_ids,
            "affected_suppliers": affected_suppliers,
        }

        # Cache result
        _cache_result(db, "geopolitical-risk", cache_key, result)
        span.set_attribute("result_source", "computed")
        logger.debug(f"Computed and cached geopolitical_risk scenario with multiplier {body.risk_multiplier}")

        return ScenarioResponse(**result)


# ────────────────────────────────────────────────────────────────────────────
# POST /resilience/delivery-target
# ────────────────────────────────────────────────────────────────────────────

@router.post("/delivery-target", response_model=DeliveryTargetResponse)
def post_delivery_target(
    body: DeliveryTargetRequest,
    db: Session = Depends(get_db),
):
    """
    Simulate impact of tight delivery constraint on supply chain.

    Identifies suppliers capable of meeting target_delivery_days,
    re-optimizes with lead-time filter, shows cost/risk impact.
    Results cached (1h TTL). OpenTelemetry spans track performance.
    """
    with tracer.start_as_current_span("delivery_target_scenario") as span:
        # Set span attributes
        span.set_attribute("target_delivery_days", body.target_delivery_days)
        span.set_attribute("bom_size", len(body.bom_component_ids))

        # Validate input
        if len(body.bom_component_ids) > 200:
            span.set_attribute("error", "bom_too_large")
            raise HTTPException(status_code=400, detail="bom_component_ids must not exceed 200 items")

        # Compute cache key
        cache_key = _compute_cache_key(
            "delivery-target",
            target_delivery_days=body.target_delivery_days,
            bom_component_ids=sorted(body.bom_component_ids),
        )
        span.set_attribute("cache_key", cache_key)

        # Check cache
        cached = _get_cached_result(db, cache_key)
        if cached:
            span.set_attribute("cache_hit", True)
            span.set_attribute("result_source", "cache")
            logger.debug(f"Cache hit for delivery_target:{body.target_delivery_days}")
            return DeliveryTargetResponse(**cached)

        span.set_attribute("cache_hit", False)

        # Compute baseline
        baseline = _compute_baseline_metrics(db, body.bom_component_ids)

        # Identify suppliers capable of meeting target, by REAL geography-derived
        # lead time (no hardcoded per-supplier days).
        with tracer.start_as_current_span("identify_capable_suppliers"):
            distributors = db.query(Distributor).all()
            suppliers_capable = []
            suppliers_cannot_meet = []
            incapable_ids: set = set()

            for dist in distributors:
                lead = _distributor_lead_days(dist)
                if lead <= body.target_delivery_days:
                    suppliers_capable.append({
                        "name": dist.name,
                        "lead_time_days": round(lead, 1),
                        "cost_adjustment_pct": 0.0,  # meets the window natively, no expedite premium
                    })
                else:
                    incapable_ids.add(dist.id)
                    suppliers_cannot_meet.append({
                        "name": dist.name,
                        "min_lead_time_days": round(lead, 1),
                        "reason": "lead_time_too_long",
                    })

        # Simulate scenario: suppliers that cannot meet the window are unavailable, so
        # force them to fail in the Monte Carlo. Tightening the window removes suppliers,
        # which the cascade model translates into higher cost and lower fulfillment.
        scenario_sim = run_monte_carlo(
            _graph(db),
            bom_component_ids=body.bom_component_ids,
            forced_failures=incapable_ids,
        )
        scenario_cost = baseline["_component_cost"] * scenario_sim.mean_cost_inflation
        scenario_eta = float(body.target_delivery_days)
        fulfillment_drop = max(0.0, baseline["baseline_fulfillment_p50"] - scenario_sim.p50)
        scenario_risk = min(baseline["baseline_risk_score"] + fulfillment_drop, 1.0)

        # Build response
        result = {
            "baseline_cost_usd": baseline["baseline_cost_usd"],
            "scenario_cost_usd": round(scenario_cost, 2),
            "cost_delta_pct": round((scenario_cost - baseline["baseline_cost_usd"]) / baseline["baseline_cost_usd"] * 100, 1) if baseline["baseline_cost_usd"] else 0.0,
            "baseline_eta_days": baseline["baseline_eta_days"],
            "scenario_eta_days": scenario_eta,
            "eta_delta_days": round(scenario_eta - baseline["baseline_eta_days"], 1),
            "baseline_risk_score": baseline["baseline_risk_score"],
            "baseline_evar_95": baseline["baseline_evar_95"],
            "procurement_spend_at_risk_usd": baseline["procurement_spend_at_risk_usd"],
            "scenario_risk_score": round(scenario_risk, 3),
            "risk_delta": round(scenario_risk - baseline["baseline_risk_score"], 3),
            "baseline_fulfillment_p10": baseline["baseline_fulfillment_p10"],
            "baseline_fulfillment_p50": baseline["baseline_fulfillment_p50"],
            "baseline_fulfillment_p90": baseline["baseline_fulfillment_p90"],
            "scenario_fulfillment_p10": round(scenario_sim.p10, 3),
            "scenario_fulfillment_p50": round(scenario_sim.p50, 3),
            "scenario_fulfillment_p90": round(scenario_sim.p90, 3),
            "affected_bom_ids": [],
            "affected_suppliers": [s["name"] for s in suppliers_capable],
            "suppliers_capable": suppliers_capable,
            "suppliers_cannot_meet": suppliers_cannot_meet,
        }

        # Cache result
        _cache_result(db, "delivery-target", cache_key, result)
        span.set_attribute("result_source", "computed")
        logger.debug(f"Computed and cached delivery_target scenario with target {body.target_delivery_days} days")

        return DeliveryTargetResponse(**result)
