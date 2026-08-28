"""
Optimization API endpoints — thin wiring over app.optimization.solve.

See docs/OPTIMIZATION_DESIGN.md.
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
from app.optimization.countries import _acled_country_key


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
            # getattr so this keeps working both before and after the migration
            # that adds the richer DigiKey columns to Component.
            category=c.category,
            dk_category=getattr(c, "digikey_category", None),
            dk_subcategory=getattr(c, "digikey_subcategory", None),
            manufacturer=getattr(c, "manufacturer", None),
            lifecycle_status=getattr(c, "lifecycle_status", None),
            is_normally_stocked=getattr(c, "normally_stocked", None),
            parameter_count=getattr(c, "parameter_count", None),
            package_case=getattr(c, "package_case", None),
            htsus_code=getattr(c, "htsus_code", None),
            rohs_status=getattr(c, "rohs_status", None),
            digikey_unit_price=getattr(c, "digikey_unit_price", None),
            max_break_qty=getattr(c, "max_break_qty", None),
            price_break_count=getattr(c, "price_break_count", None),
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
            # WITHOUT this the dataclass default "US" applied to all 92 distributors,
            # including the ~31 in China, so sourcing._feed_risk_obj_units asked ACLED
            # about the United States for every single offer and geopolitical
            # conflict risk was country-blind on the live /optimize/vrp path.
            distributor_country=_acled_country_key(d.country),
            # getattr so this keeps working both before and after the migration
            # that adds the richer DigiKey columns to DistributorOffer.
            packaging=getattr(o, "packaging", None),
            standard_pack=getattr(o, "standard_pack", None),
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Solver failed: {e}") from e

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


# ── REMOVED: POST /optimize/scenario ─────────────────────────────────────────
#
# The "digital twin" what-if endpoint that used to live here is deleted, not fixed.
#
# WHAT IT DID WRONG. It priced a disruption by DROPPING the unavailable cart lines
# from the total: `scenario_cost` was set to None whenever the distributor was in
# `distributor_failure_ids`, and the total then summed only the surviving lines. So
# failing eight distributors returned `cost_delta_pct: -76.4` -- losing three quarters
# of your suppliers made you 76% cheaper, because unmet demand cost exactly zero and
# nothing was ever re-sourced. It was labelled "(simplified)" and shipped live.
#
# WHY DELETED RATHER THAN REPAIRED. Repairing it means giving unmet demand a price and
# re-sourcing the gap from surviving suppliers -- which is precisely the two-stage
# stochastic program in `app/optimization/stochastic.py`, exposed at
# `POST /api/v1/stochastic/frontier`. That model has an actual recourse decision
# (emergency re-procurement from survivors at a premium, drawing on residual stock,
# with an expedited-consignment fixed cost), prices what cannot be covered at
# `STOCKOUT_PENALTY_MULTIPLE x the dearest emergency route`, and reports the whole
# cost-vs-CVaR curve rather than one hard-coded what-if. Keeping a second, wrong answer
# to the same question next to it would only invite someone to quote the wrong one.
#
# Consumers at deletion time: none. `frontend/src/pages/DigitalTwinPage.tsx` (its only
# caller) is gone; the `optimizeAPI.scenario` helper in `frontend/src/services/api.ts`
# is exported but called from nowhere and should be removed with it. No test, seed
# script or document referenced the route.
