from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_db
from app.models.material import Material, PriceHistory, PriceForecast
from app.models.supplier import Supplier

router = APIRouter(prefix="/materials", tags=["materials"])


class MaterialResponse(BaseModel):
    id: int
    name: str
    category: str
    subcategory: Optional[str]
    unit: str
    description: Optional[str]
    current_price: Optional[float]
    price_unit: Optional[str]
    volatility_score: float
    supply_risk_score: float

    class Config:
        from_attributes = True


class PricePoint(BaseModel):
    date: datetime
    price: float
    source: Optional[str]

    class Config:
        from_attributes = True


class ForecastPoint(BaseModel):
    forecast_date: datetime
    predicted_price: float
    lower_ci: Optional[float]
    upper_ci: Optional[float]

    class Config:
        from_attributes = True


class SupplierRecommendation(BaseModel):
    id: int
    name: str
    city: Optional[str]
    state: Optional[str]
    lead_time_days: int
    reliability_score: float
    risk_score: float
    price_competitiveness: float
    composite_score: float  # weighted recommendation score
    is_domestic: bool


@router.get("", response_model=List[MaterialResponse])
async def list_materials(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """List all materials, with optional category filter and search."""
    q = db.query(Material)
    if category:
        q = q.filter(Material.category == category)
    if search:
        q = q.filter(Material.name.ilike(f"%{search}%"))
    return q.offset(skip).limit(limit).all()


@router.get("/categories")
async def list_categories(db: Session = Depends(get_db)):
    """Return distinct category names."""
    rows = db.query(Material.category).distinct().all()
    return [r[0] for r in rows]


@router.get("/{material_id}", response_model=MaterialResponse)
async def get_material(material_id: int, db: Session = Depends(get_db)):
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    return m


@router.get("/{material_id}/price-history", response_model=List[PricePoint])
async def get_price_history(
    material_id: int,
    days: int = Query(90, ge=7, le=730),
    db: Session = Depends(get_db),
):
    """Return last N days of price history for sparkline charts."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.material_id == material_id, PriceHistory.date >= cutoff)
        .order_by(PriceHistory.date)
        .all()
    )
    return rows


@router.get("/{material_id}/forecast", response_model=List[ForecastPoint])
async def get_forecast(material_id: int, db: Session = Depends(get_db)):
    """Return 90-day Prophet price forecast with confidence intervals."""
    rows = (
        db.query(PriceForecast)
        .filter(PriceForecast.material_id == material_id)
        .order_by(PriceForecast.forecast_date)
        .limit(90)
        .all()
    )
    if not rows:
        # Generate a simple linear forecast from recent history as fallback
        from datetime import timedelta
        hist = (
            db.query(PriceHistory)
            .filter(PriceHistory.material_id == material_id)
            .order_by(PriceHistory.date.desc())
            .limit(30)
            .all()
        )
        if not hist:
            raise HTTPException(status_code=404, detail="No forecast or price history available")
        avg_price = sum(h.price for h in hist) / len(hist)
        result = []
        for i in range(1, 91):
            result.append(ForecastPoint(
                forecast_date=datetime.utcnow() + timedelta(days=i),
                predicted_price=avg_price,
                lower_ci=avg_price * 0.92,
                upper_ci=avg_price * 1.08,
            ))
        return result
    return rows


@router.get("/{material_id}/suppliers", response_model=List[SupplierRecommendation])
async def get_suppliers(material_id: int, db: Session = Depends(get_db)):
    """Return ranked supplier recommendations for a material.

    Score = 0.4*price_competitiveness + 0.3*reliability + 0.2*(1-lead_time_norm) + 0.1*(1-risk)
    """
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")

    # Filter suppliers that handle this material (stored as comma-separated IDs)
    all_suppliers = db.query(Supplier).all()
    relevant = []
    for s in all_suppliers:
        ids = [int(x) for x in (s.materials_supplied or "").split(",") if x.strip().isdigit()]
        if material_id in ids:
            relevant.append(s)

    if not relevant:
        # Fallback: return all suppliers from nearby hubs
        relevant = db.query(Supplier).limit(10).all()

    max_lead = max((s.lead_time_days for s in relevant), default=30)
    results = []
    for s in relevant:
        lead_norm = s.lead_time_days / max_lead if max_lead else 0
        composite = (
            0.4 * s.price_competitiveness
            + 0.3 * s.reliability_score
            + 0.2 * (1 - lead_norm)
            + 0.1 * (1 - s.risk_score)
        )
        results.append(SupplierRecommendation(
            id=s.id,
            name=s.name,
            city=s.city,
            state=s.state,
            lead_time_days=s.lead_time_days,
            reliability_score=s.reliability_score,
            risk_score=s.risk_score,
            price_competitiveness=s.price_competitiveness,
            composite_score=round(composite, 3),
            is_domestic=s.is_domestic,
        ))
    results.sort(key=lambda x: x.composite_score, reverse=True)
    return results
