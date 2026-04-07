from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.hub import ProductionHub
from app.models.supplier import Supplier

router = APIRouter(prefix="/hubs", tags=["hubs"])


class HubResponse(BaseModel):
    id: int
    name: str
    city: str
    state: str
    latitude: float
    longitude: float
    hub_type: Optional[str]
    specialization: Optional[str]
    description: Optional[str]
    active_suppliers: int
    risk_index: float

    class Config:
        from_attributes = True


class SupplierBrief(BaseModel):
    id: int
    name: str
    lead_time_days: int
    reliability_score: float
    risk_score: float
    is_domestic: bool
    materials_supplied: Optional[str]

    class Config:
        from_attributes = True


class HubDetail(HubResponse):
    suppliers: List[SupplierBrief] = []


@router.get("", response_model=List[HubResponse])
async def list_hubs(db: Session = Depends(get_db)):
    """Return all 25 US production hubs for map rendering."""
    hubs = db.query(ProductionHub).all()
    return hubs


@router.get("/{hub_id}", response_model=HubDetail)
async def get_hub(hub_id: int, db: Session = Depends(get_db)):
    """Hub detail: metadata + supplier list for tooltip/sidebar."""
    hub = db.query(ProductionHub).filter(ProductionHub.id == hub_id).first()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    suppliers = db.query(Supplier).filter(Supplier.hub_id == hub_id).limit(20).all()
    hub_data = HubDetail.model_validate(hub)
    hub_data.suppliers = [SupplierBrief.model_validate(s) for s in suppliers]
    return hub_data


class NearbyRequest(BaseModel):
    latitude: float
    longitude: float
    radius_km: float = 500.0


@router.post("/nearby", response_model=List[HubResponse])
async def find_nearby_hubs(body: NearbyRequest, db: Session = Depends(get_db)):
    """Find production hubs within radius_km of factory coordinates."""
    # Haversine approximation: 1 degree lat ≈ 111 km
    lat_delta = body.radius_km / 111.0
    lng_delta = body.radius_km / (111.0 * abs(
        __import__("math").cos(__import__("math").radians(body.latitude))
    ) or 1)
    hubs = db.query(ProductionHub).filter(
        ProductionHub.latitude.between(body.latitude - lat_delta, body.latitude + lat_delta),
        ProductionHub.longitude.between(body.longitude - lng_delta, body.longitude + lng_delta),
    ).all()
    return hubs
