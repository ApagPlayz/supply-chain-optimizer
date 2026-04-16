from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sqla_func
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor

router = APIRouter(prefix="/components", tags=["components"])


class ComponentResponse(BaseModel):
    id: int
    mpn: str
    manufacturer: str
    manufacturer_country: Optional[str]
    category: str
    description: Optional[str]
    risk_score: float
    risk_factors: Optional[list]
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    num_offers: int = 0

    class Config:
        from_attributes = True


class OfferResponse(BaseModel):
    id: int
    distributor_id: int
    distributor_name: str
    distributor_city: Optional[str]
    distributor_state: Optional[str]
    distributor_country: Optional[str]
    is_domestic: bool
    price: float
    stock: int
    moq: int = 1
    sku: Optional[str]
    currency: Optional[str]

    class Config:
        from_attributes = True


class ComponentDetailResponse(BaseModel):
    id: int
    mpn: str
    manufacturer: str
    manufacturer_country: Optional[str]
    category: str
    description: Optional[str]
    datasheets: Optional[list]
    risk_score: float
    risk_factors: Optional[list]
    offers: List[OfferResponse]

    class Config:
        from_attributes = True


@router.get("", response_model=List[ComponentResponse])
async def list_components(
    category: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 1000,
    db: Session = Depends(get_db),
):
    """List components with optional filters. Includes price range and offer count.

    Uses a subquery aggregation over DistributorOffer joined to Component to
    avoid the previous N+1 query pattern (one offer query per component).
    """
    # Subquery: aggregate offer stats per component in a single pass.
    offer_stats = (
        db.query(
            DistributorOffer.component_id,
            sqla_func.min(DistributorOffer.price).label("min_price"),
            sqla_func.max(DistributorOffer.price).label("max_price"),
            sqla_func.count(DistributorOffer.id).label("num_offers"),
        )
        .filter(DistributorOffer.price > 0)
        .group_by(DistributorOffer.component_id)
        .subquery()
    )

    q = (
        db.query(
            Component,
            offer_stats.c.min_price,
            offer_stats.c.max_price,
            offer_stats.c.num_offers,
        )
        .outerjoin(offer_stats, Component.id == offer_stats.c.component_id)
    )

    if category:
        q = q.filter(Component.category == category)
    if manufacturer:
        q = q.filter(Component.manufacturer == manufacturer)
    if search:
        q = q.filter(
            Component.mpn.ilike(f"%{search}%")
            | Component.description.ilike(f"%{search}%")
            | Component.manufacturer.ilike(f"%{search}%")
        )

    rows = q.offset(skip).limit(limit).all()

    results = []
    for c, min_price, max_price, num_offers in rows:
        results.append(ComponentResponse(
            id=c.id,
            mpn=c.mpn,
            manufacturer=c.manufacturer,
            manufacturer_country=c.manufacturer_country,
            category=c.category,
            description=c.description,
            risk_score=c.risk_score,
            risk_factors=c.risk_factors,
            min_price=float(min_price) if min_price is not None else None,
            max_price=float(max_price) if max_price is not None else None,
            num_offers=int(num_offers) if num_offers is not None else 0,
        ))
    return results


@router.get("/categories")
async def list_categories(db: Session = Depends(get_db)):
    """Return distinct component categories with counts."""
    rows = (
        db.query(Component.category, sqla_func.count(Component.id))
        .group_by(Component.category)
        .order_by(sqla_func.count(Component.id).desc())
        .all()
    )
    return [{"name": name, "count": count} for name, count in rows]


@router.get("/manufacturers")
async def list_manufacturers(db: Session = Depends(get_db)):
    """Return distinct manufacturers with counts."""
    rows = (
        db.query(Component.manufacturer, sqla_func.count(Component.id))
        .group_by(Component.manufacturer)
        .order_by(sqla_func.count(Component.id).desc())
        .all()
    )
    return [{"name": name, "count": count} for name, count in rows]


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Dashboard stats: total components, distributors, offers, etc."""
    comp_count = db.query(Component).count()
    dist_count = db.query(Distributor).count()
    offer_count = db.query(DistributorOffer).count()
    domestic_count = db.query(Distributor).filter(Distributor.is_domestic == True).count()
    categories = db.query(Component.category).distinct().count()
    manufacturers = db.query(Component.manufacturer).distinct().count()

    return {
        "total_components": comp_count,
        "total_distributors": dist_count,
        "domestic_distributors": domestic_count,
        "international_distributors": dist_count - domestic_count,
        "total_offers": offer_count,
        "categories": categories,
        "manufacturers": manufacturers,
        "avg_offers_per_component": round(offer_count / max(comp_count, 1), 1),
    }


@router.get("/{component_id}", response_model=ComponentDetailResponse)
async def get_component(component_id: int, db: Session = Depends(get_db)):
    """Get component detail with all distributor offers ranked by price."""
    c = db.query(Component).filter(Component.id == component_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Component not found")

    offers_raw = (
        db.query(DistributorOffer, Distributor)
        .join(Distributor, DistributorOffer.distributor_id == Distributor.id)
        .filter(DistributorOffer.component_id == component_id)
        .order_by(DistributorOffer.price.asc())
        .all()
    )

    offers = [
        OfferResponse(
            id=o.id,
            distributor_id=d.id,
            distributor_name=d.name,
            distributor_city=d.city,
            distributor_state=d.state,
            distributor_country=d.country,
            is_domestic=d.is_domestic,
            price=o.price,
            stock=o.stock,
            moq=int(o.moq or 1),
            sku=o.sku,
            currency=o.currency,
        )
        for o, d in offers_raw
    ]

    return ComponentDetailResponse(
        id=c.id,
        mpn=c.mpn,
        manufacturer=c.manufacturer,
        manufacturer_country=c.manufacturer_country,
        category=c.category,
        description=c.description,
        datasheets=c.datasheets,
        risk_score=c.risk_score,
        risk_factors=c.risk_factors,
        offers=offers,
    )


@router.get("/{component_id}/offers", response_model=List[OfferResponse])
async def get_offers(
    component_id: int,
    sort_by: str = Query("price", pattern="^(price|stock|distributor_name)$"),
    domestic_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Get ranked distributor offers for a component."""
    c = db.query(Component).filter(Component.id == component_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Component not found")

    q = (
        db.query(DistributorOffer, Distributor)
        .join(Distributor, DistributorOffer.distributor_id == Distributor.id)
        .filter(DistributorOffer.component_id == component_id)
    )

    if domestic_only:
        q = q.filter(Distributor.is_domestic == True)

    if sort_by == "price":
        q = q.order_by(DistributorOffer.price.asc())
    elif sort_by == "stock":
        q = q.order_by(DistributorOffer.stock.desc())
    else:
        q = q.order_by(Distributor.name.asc())

    return [
        OfferResponse(
            id=o.id,
            distributor_id=d.id,
            distributor_name=d.name,
            distributor_city=d.city,
            distributor_state=d.state,
            distributor_country=d.country,
            is_domestic=d.is_domestic,
            price=o.price,
            stock=o.stock,
            moq=int(o.moq or 1),
            sku=o.sku,
            currency=o.currency,
        )
        for o, d in q.all()
    ]
