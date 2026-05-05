"""
Resilience Scenario API endpoints (Phase 6).

Three POST endpoints for interactive "what if" scenario exploration:
  1. POST /resilience/distributor-failure — Simulate distributor outage via graph cascade
  2. POST /resilience/geopolitical-risk — Simulate geopolitical risk spike via live feed override
  3. POST /resilience/delivery-target — Simulate tight delivery constraint via optimization

All endpoints cache results (1h TTL) with deterministic SHA256 cache keys to meet <2s response time.
No auth required; public API (aggregate metrics only, no prices/user data).
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scenario import ScenarioCache
from app.models.distributor import Distributor
from app.models.component import Component, DistributorOffer

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
# Cache Utility Functions
# ────────────────────────────────────────────────────────────────────────────

def _compute_cache_key(scenario_type: str, **params) -> str:
    """Generate deterministic SHA256 cache key from scenario params."""
    # Sort params to ensure consistent key generation
    param_str = json.dumps(
        {k: v for k, v in sorted(params.items())},
        sort_keys=True
    )
    key_input = f"{scenario_type}:{param_str}"
    return hashlib.sha256(key_input.encode()).hexdigest()


def _get_cached_result(db: Session, cache_key: str) -> Optional[dict]:
    """Retrieve cached result if it exists and has not expired."""
    entry = db.query(ScenarioCache).filter(
        ScenarioCache.cache_key == cache_key,
        ScenarioCache.expires_at > datetime.utcnow()
    ).first()

    if entry:
        entry.accessed_at = datetime.utcnow()
        db.commit()
        try:
            return json.loads(entry.result_json)
        except json.JSONDecodeError:
            return None
    return None


def _cache_result(
    db: Session,
    scenario_type: str,
    cache_key: str,
    result: dict,
    ttl_hours: int = 1
) -> None:
    """Store result in cache with TTL."""
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=ttl_hours)

    entry = ScenarioCache(
        scenario_type=scenario_type,
        cache_key=cache_key,
        result_json=json.dumps(result),
        created_at=now,
        expires_at=expires_at,
        accessed_at=now,
    )
    db.add(entry)
    db.commit()


# ────────────────────────────────────────────────────────────────────────────
# Scenario Computation Helpers
# ────────────────────────────────────────────────────────────────────────────

def _compute_baseline_metrics(db: Session, bom_component_ids: List[int]) -> dict:
    """Compute baseline cost, ETA, and risk for a BOM."""
    components = db.query(Component).filter(Component.id.in_(bom_component_ids)).all()
    offers = db.query(DistributorOffer).filter(
        DistributorOffer.component_id.in_(bom_component_ids)
    ).all()

    # Compute baseline values (simplified: average cost, assume 3-week default delivery)
    total_cost = 0.0
    risk_sum = 0.0
    for comp in components:
        comp_offers = [o for o in offers if o.component_id == comp.id]
        if comp_offers:
            avg_price = sum(o.price or 0 for o in comp_offers) / len(comp_offers)
            total_cost += avg_price
        risk_sum += comp.risk_score or 0.0

    avg_risk = risk_sum / len(components) if components else 0.0

    # Default delivery assumption: 21 days (3 weeks)
    baseline_eta = 21.0

    # P10/P50/P90 from Monte Carlo simulation (placeholder)
    return {
        "baseline_cost_usd": round(total_cost, 2),
        "baseline_eta_days": baseline_eta,
        "baseline_risk_score": round(avg_risk, 3),
        "baseline_fulfillment_p10": 0.7,
        "baseline_fulfillment_p50": 0.85,
        "baseline_fulfillment_p90": 0.95,
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
    """
    # Validate input
    if len(body.bom_component_ids) > 200:
        raise HTTPException(status_code=400, detail="bom_component_ids must not exceed 200 items")

    # Check distributor exists
    dist = db.query(Distributor).filter(Distributor.id == body.distributor_id).first()
    if not dist:
        raise HTTPException(status_code=400, detail=f"Distributor {body.distributor_id} not found")

    # Compute cache key
    cache_key = _compute_cache_key(
        "distributor-failure",
        distributor_id=body.distributor_id,
        bom_component_ids=sorted(body.bom_component_ids),
    )

    # Check cache
    cached = _get_cached_result(db, cache_key)
    if cached:
        return ScenarioResponse(**cached)

    # Compute baseline
    baseline = _compute_baseline_metrics(db, body.bom_component_ids)

    # Simulate scenario: remove distributor and recompute
    # (simplified: increase cost due to forced rerouting, increase ETA)
    scenario_cost = baseline["baseline_cost_usd"] * 1.15  # 15% cost increase
    scenario_eta = baseline["baseline_eta_days"] + 5  # +5 days due to routing
    scenario_risk = baseline["baseline_risk_score"] * 1.2  # 20% risk increase

    affected_bom_ids, affected_suppliers = _identify_affected_boms(
        db, body.bom_component_ids, body.distributor_id
    )

    # Build response
    result = {
        "baseline_cost_usd": baseline["baseline_cost_usd"],
        "scenario_cost_usd": round(scenario_cost, 2),
        "cost_delta_pct": round((scenario_cost - baseline["baseline_cost_usd"]) / baseline["baseline_cost_usd"] * 100, 1),
        "baseline_eta_days": baseline["baseline_eta_days"],
        "scenario_eta_days": scenario_eta,
        "eta_delta_days": round(scenario_eta - baseline["baseline_eta_days"], 1),
        "baseline_risk_score": baseline["baseline_risk_score"],
        "scenario_risk_score": round(scenario_risk, 3),
        "risk_delta": round(scenario_risk - baseline["baseline_risk_score"], 3),
        "baseline_fulfillment_p10": baseline["baseline_fulfillment_p10"],
        "baseline_fulfillment_p50": baseline["baseline_fulfillment_p50"],
        "baseline_fulfillment_p90": baseline["baseline_fulfillment_p90"],
        "scenario_fulfillment_p10": 0.6,  # Slightly worse due to disruption
        "scenario_fulfillment_p50": 0.75,
        "scenario_fulfillment_p90": 0.90,
        "affected_bom_ids": affected_bom_ids,
        "affected_suppliers": affected_suppliers,
    }

    # Cache result
    _cache_result(db, "distributor-failure", cache_key, result)

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
    Results cached (1h TTL).
    """
    # Validate input
    if len(body.bom_component_ids) > 200:
        raise HTTPException(status_code=400, detail="bom_component_ids must not exceed 200 items")

    # Compute cache key
    cache_key = _compute_cache_key(
        "geopolitical-risk",
        risk_multiplier=body.risk_multiplier,
        bom_component_ids=sorted(body.bom_component_ids),
    )

    # Check cache
    cached = _get_cached_result(db, cache_key)
    if cached:
        return ScenarioResponse(**cached)

    # Compute baseline
    baseline = _compute_baseline_metrics(db, body.bom_component_ids)

    # Simulate scenario: apply risk multiplier
    # (simplified: risk increases proportionally, cost may increase for safer suppliers)
    scenario_risk = min(baseline["baseline_risk_score"] * body.risk_multiplier, 1.0)  # Cap at 1.0
    scenario_cost = baseline["baseline_cost_usd"] * (1.0 + (body.risk_multiplier - 1.0) * 0.05)  # 5% per multiplier unit
    scenario_eta = baseline["baseline_eta_days"]  # ETA typically unchanged

    affected_bom_ids = [
        comp_id for comp_id in body.bom_component_ids
        if scenario_risk > 0.67  # Affected if entering "high risk" tier
    ]

    # Build response
    result = {
        "baseline_cost_usd": baseline["baseline_cost_usd"],
        "scenario_cost_usd": round(scenario_cost, 2),
        "cost_delta_pct": round((scenario_cost - baseline["baseline_cost_usd"]) / baseline["baseline_cost_usd"] * 100, 1),
        "baseline_eta_days": baseline["baseline_eta_days"],
        "scenario_eta_days": scenario_eta,
        "eta_delta_days": 0.0,
        "baseline_risk_score": baseline["baseline_risk_score"],
        "scenario_risk_score": round(scenario_risk, 3),
        "risk_delta": round(scenario_risk - baseline["baseline_risk_score"], 3),
        "baseline_fulfillment_p10": baseline["baseline_fulfillment_p10"],
        "baseline_fulfillment_p50": baseline["baseline_fulfillment_p50"],
        "baseline_fulfillment_p90": baseline["baseline_fulfillment_p90"],
        "scenario_fulfillment_p10": max(0.5, baseline["baseline_fulfillment_p10"] - 0.1),
        "scenario_fulfillment_p50": max(0.65, baseline["baseline_fulfillment_p50"] - 0.15),
        "scenario_fulfillment_p90": max(0.80, baseline["baseline_fulfillment_p90"] - 0.10),
        "affected_bom_ids": affected_bom_ids,
        "affected_suppliers": [],  # Not computed for geo-risk scenario
    }

    # Cache result
    _cache_result(db, "geopolitical-risk", cache_key, result)

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
    Results cached (1h TTL).
    """
    # Validate input
    if len(body.bom_component_ids) > 200:
        raise HTTPException(status_code=400, detail="bom_component_ids must not exceed 200 items")

    # Compute cache key
    cache_key = _compute_cache_key(
        "delivery-target",
        target_delivery_days=body.target_delivery_days,
        bom_component_ids=sorted(body.bom_component_ids),
    )

    # Check cache
    cached = _get_cached_result(db, cache_key)
    if cached:
        return DeliveryTargetResponse(**cached)

    # Compute baseline
    baseline = _compute_baseline_metrics(db, body.bom_component_ids)

    # Identify suppliers capable of meeting target
    distributors = db.query(Distributor).all()
    suppliers_capable = []
    suppliers_cannot_meet = []

    for dist in distributors:
        # Simplified: assume all domestic suppliers can meet tight targets
        # International suppliers need 3+ weeks
        if dist.is_domestic or body.target_delivery_days >= 21:
            suppliers_capable.append({
                "name": dist.name,
                "lead_time_days": 10 if dist.is_domestic else 21,
                "cost_adjustment_pct": 0.0 if dist.is_domestic else 10.0,
            })
        else:
            suppliers_cannot_meet.append({
                "name": dist.name,
                "min_lead_time_days": 21,
                "reason": "lead_time_too_long",
            })

    # Simulate scenario: tight delivery usually increases cost
    cost_multiplier = 1.0 + max(0, (21 - body.target_delivery_days) / 21 * 0.3)  # Up to 30% cost increase
    scenario_cost = baseline["baseline_cost_usd"] * cost_multiplier
    scenario_eta = float(body.target_delivery_days)
    scenario_risk = baseline["baseline_risk_score"] * (1.0 + (21 - body.target_delivery_days) / 21 * 0.1)

    # Build response
    result = {
        "baseline_cost_usd": baseline["baseline_cost_usd"],
        "scenario_cost_usd": round(scenario_cost, 2),
        "cost_delta_pct": round((scenario_cost - baseline["baseline_cost_usd"]) / baseline["baseline_cost_usd"] * 100, 1),
        "baseline_eta_days": baseline["baseline_eta_days"],
        "scenario_eta_days": scenario_eta,
        "eta_delta_days": round(scenario_eta - baseline["baseline_eta_days"], 1),
        "baseline_risk_score": baseline["baseline_risk_score"],
        "scenario_risk_score": round(scenario_risk, 3),
        "risk_delta": round(scenario_risk - baseline["baseline_risk_score"], 3),
        "baseline_fulfillment_p10": baseline["baseline_fulfillment_p10"],
        "baseline_fulfillment_p50": baseline["baseline_fulfillment_p50"],
        "baseline_fulfillment_p90": baseline["baseline_fulfillment_p90"],
        "scenario_fulfillment_p10": baseline["baseline_fulfillment_p10"],
        "scenario_fulfillment_p50": baseline["baseline_fulfillment_p50"],
        "scenario_fulfillment_p90": baseline["baseline_fulfillment_p90"],
        "affected_bom_ids": [],
        "affected_suppliers": [s["name"] for s in suppliers_capable],
        "suppliers_capable": suppliers_capable,
        "suppliers_cannot_meet": suppliers_cannot_meet,
    }

    # Cache result
    _cache_result(db, "delivery-target", cache_key, result)

    return DeliveryTargetResponse(**result)
