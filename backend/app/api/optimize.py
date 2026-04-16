"""
Optimization API endpoints — thin wiring over app.optimization.solve.

See docs/superpowers/specs/2026-04-10-sub-project-a-design.md.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.database import get_db
from app.models.component import Component, DistributorOffer
from app.models.cross_dock_hub import CrossDockHub
from app.models.distributor import Distributor
from app.models.order import CartItem, Order
from app.models.user import User
from app.optimization import schemas as opt_schemas
from app.optimization.costs import haversine_km
from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer


router = APIRouter(prefix="/optimize", tags=["optimization"])


def _distributor_tier(total_offers: int) -> str:
    if total_offers >= 500:
        return "major"
    if total_offers >= 100:
        return "mid"
    return "broker"


class VrpRequest(BaseModel):
    us_only: bool = False  # global override: restrict ALL strategies to domestic suppliers
    graph_aware: bool = False  # per D-GRAPH-08: pass graph surcharge flag to CP-SAT solver


@router.post("/vrp", response_model=opt_schemas.MultiRouteResponse)
def optimize_route(
    body: VrpRequest = VrpRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run the full sourcing + TSP + cross-dock pipeline for the user's cart."""
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Build BOM from cart
    bom: List[BomLine] = []
    comp_ids = [ci.component_id for ci in cart_items]
    components = {
        c.id: c for c in db.query(Component).filter(Component.id.in_(comp_ids)).all()
    }
    for ci in cart_items:
        c = components.get(ci.component_id)
        if not c:
            continue
        bom.append(BomLine(
            component_id=c.id,
            mpn=c.mpn,
            quantity=int(ci.quantity),
        ))

    if not bom:
        raise HTTPException(status_code=400, detail="No valid components in cart")

    # Fetch all offers for these components (let the solver filter)
    offer_rows = db.query(DistributorOffer).filter(
        DistributorOffer.component_id.in_(comp_ids)
    ).all()

    # Distributor metadata cache
    dist_ids = {o.distributor_id for o in offer_rows}
    dist_rows = db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
    dist_by_id = {d.id: d for d in dist_rows}

    depot = GeoPoint(lat=float(current_user.latitude), lng=float(current_user.longitude))

    offers: List[Offer] = []
    for o in offer_rows:
        d = dist_by_id.get(o.distributor_id)
        if not d or o.price is None or o.price <= 0:
            continue
        comp = components.get(o.component_id)
        is_chinese = any(
            "chinese" in str(f).lower()
            for f in ((comp.risk_factors if comp else None) or [])
        )
        offers.append(Offer(
            component_id=o.component_id,
            distributor_id=o.distributor_id,
            distributor_name=d.name,
            price_usd=float(o.price),
            stock=int(o.stock or 0),
            moq=int(o.moq or 1),
            is_domestic=bool(d.is_domestic),
            dist_km_from_depot=haversine_km(
                depot.lat, depot.lng, d.latitude, d.longitude
            ),
            risk_score=float(comp.risk_score if comp else 0.5),
            is_chinese_origin=is_chinese,
        ))

    distributors_meta = {
        d.id: DistributorMeta(
            id=d.id, name=d.name, lat=d.latitude, lng=d.longitude,
            city=d.city, state=d.state, country=d.country,
            is_domestic=bool(d.is_domestic),
            tier=_distributor_tier(d.total_offers or 0),
        )
        for d in dist_rows
    }

    try:
        response = optimize_bom(bom, offers, distributors_meta, depot, us_only=body.us_only, graph_aware=body.graph_aware)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Solver failed: {e}")

    # Persist balanced alternative as an order record
    balanced = next(a for a in response.alternatives if a.id == "balanced")
    order = Order(
        user_id=current_user.id,
        status="optimized",
        total_cost=balanced.total_cost_usd,
        total_co2e_kg=balanced.total_co2e_kg,
        eta_days=balanced.base_eta_days,
        eta_lower_ci=balanced.eta_p10,
        eta_upper_ci=balanced.eta_p90,
        optimized_route=[s.model_dump() for s in balanced.route],
        monte_carlo_results={"p10": balanced.eta_p10, "p50": balanced.eta_p50, "p90": balanced.eta_p90},
        items=[{"component_id": ci.component_id, "distributor_id": ci.distributor_id,
                "quantity": ci.quantity, "unit_price": ci.unit_price} for ci in cart_items],
    )
    db.add(order)
    db.commit()

    return response


class HubOut(BaseModel):
    id: int
    name: str
    operator: Optional[str]
    hub_type: Optional[str]
    city: Optional[str]
    state: Optional[str]
    latitude: float
    longitude: float


@router.get("/hubs", response_model=List[HubOut])
def list_cross_dock_hubs(db: Session = Depends(get_db)):
    """Return the 10 real US freight hubs for map display."""
    return [
        HubOut(
            id=h.id, name=h.name, operator=h.operator, hub_type=h.hub_type,
            city=h.city, state=h.state,
            latitude=h.latitude, longitude=h.longitude,
        )
        for h in db.query(CrossDockHub).order_by(CrossDockHub.id).all()
    ]


# Legacy scenario endpoint (retained verbatim — not part of Sub-Project A)

class ScenarioRequest(BaseModel):
    tariff_multiplier: float = 1.0
    distributor_failure_ids: List[int] = []
    demand_spike: float = 1.0


@router.post("/scenario")
def run_scenario(
    body: ScenarioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Digital twin: re-run optimization under what-if conditions (simplified)."""
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    adjustments = []
    for item in cart_items:
        dist = db.query(Distributor).filter(Distributor.id == item.distributor_id).first()
        comp = db.query(Component).filter(Component.id == item.component_id).first()
        base_price = item.unit_price or 0
        tariff_adj = base_price * body.tariff_multiplier
        dist_failed = item.distributor_id in body.distributor_failure_ids
        adjustments.append({
            "component": comp.mpn if comp else "Unknown",
            "distributor": dist.name if dist else "Unknown",
            "base_price": base_price,
            "scenario_price": tariff_adj if not dist_failed else None,
            "distributor_available": not dist_failed,
            "quantity": item.quantity,
            "base_cost": base_price * item.quantity,
            "scenario_cost": tariff_adj * item.quantity * body.demand_spike if not dist_failed else None,
        })

    base_total = sum(a["base_cost"] for a in adjustments)
    scenario_total = sum(a["scenario_cost"] for a in adjustments if a["scenario_cost"] is not None)
    cost_delta_pct = round((scenario_total - base_total) / base_total * 100, 1) if base_total else 0

    return {
        "scenario": {
            "tariff_multiplier": body.tariff_multiplier,
            "distributor_failures": len(body.distributor_failure_ids),
            "demand_spike": body.demand_spike,
        },
        "base_total_cost": round(base_total, 2),
        "scenario_total_cost": round(scenario_total, 2),
        "cost_delta_pct": cost_delta_pct,
        "disrupted_items": len([a for a in adjustments if not a["distributor_available"]]),
        "item_breakdown": adjustments,
    }
