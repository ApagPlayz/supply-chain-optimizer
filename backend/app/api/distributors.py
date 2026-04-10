from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.distributor import Distributor
from app.models.component import DistributorOffer, Component

router = APIRouter(prefix="/distributors", tags=["distributors"])


class DistributorResponse(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    is_domestic: bool
    total_offers: int
    total_stock: int

    class Config:
        from_attributes = True


class DistributorDetailResponse(DistributorResponse):
    top_components: List[dict]  # top components by stock


@router.get("", response_model=List[DistributorResponse])
async def list_distributors(
    domestic_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    """List all distributors with their locations and stats."""
    q = db.query(Distributor)
    if domestic_only:
        q = q.filter(Distributor.is_domestic == True)
    return q.order_by(Distributor.total_offers.desc()).all()


@router.get("/{distributor_id}", response_model=DistributorDetailResponse)
async def get_distributor(distributor_id: int, db: Session = Depends(get_db)):
    """Get distributor detail with top components they carry."""
    d = db.query(Distributor).filter(Distributor.id == distributor_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Distributor not found")

    # Top 20 components by stock level at this distributor
    top = (
        db.query(DistributorOffer, Component)
        .join(Component, DistributorOffer.component_id == Component.id)
        .filter(DistributorOffer.distributor_id == distributor_id)
        .order_by(DistributorOffer.stock.desc())
        .limit(20)
        .all()
    )

    top_components = [
        {
            "component_id": c.id,
            "mpn": c.mpn,
            "manufacturer": c.manufacturer,
            "category": c.category,
            "price": o.price,
            "stock": o.stock,
            "sku": o.sku,
        }
        for o, c in top
    ]

    return DistributorDetailResponse(
        id=d.id,
        name=d.name,
        latitude=d.latitude,
        longitude=d.longitude,
        city=d.city,
        state=d.state,
        country=d.country,
        is_domestic=d.is_domestic,
        total_offers=d.total_offers,
        total_stock=d.total_stock,
        top_components=top_components,
    )
