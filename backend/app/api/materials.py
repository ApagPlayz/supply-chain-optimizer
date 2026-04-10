from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.config import settings
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
    supplier_price: Optional[float]  # supplier-specific price for this material
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


@router.get("/data-sources")
async def get_data_sources(db: Session = Depends(get_db)):
    """Show which materials have real API data vs synthetic data.

    Returns summary of data sources and API key status.
    """
    from sqlalchemy import func as sqla_func

    materials = db.query(Material).all()
    source_counts = (
        db.query(PriceHistory.source, sqla_func.count(PriceHistory.id))
        .group_by(PriceHistory.source)
        .all()
    )

    api_materials = [
        {
            "id": m.id,
            "name": m.name,
            "fred_series_id": m.fred_series_id,
            "alpha_vantage_symbol": m.alpha_vantage_symbol,
        }
        for m in materials
        if m.fred_series_id or m.alpha_vantage_symbol
    ]

    return {
        "total_materials": len(materials),
        "materials_with_api_mapping": len(api_materials),
        "api_materials": api_materials,
        "price_history_sources": {src: cnt for src, cnt in source_counts},
        "api_keys_configured": {
            "fred": bool(settings.FRED_API_KEY),
            "alpha_vantage": bool(settings.ALPHA_VANTAGE_API_KEY),
        },
    }


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

    base_price = m.current_price or 0
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
        # Supplier-specific price: base price adjusted by competitiveness
        # comp=1.0 → 0.7x (30% cheaper), comp=0.5 → 1.0x, comp=0.0 → 1.3x
        supplier_price = round(base_price * (1.3 - 0.6 * s.price_competitiveness), 2) if base_price else None
        results.append(SupplierRecommendation(
            id=s.id,
            name=s.name,
            city=s.city,
            state=s.state,
            lead_time_days=s.lead_time_days,
            reliability_score=s.reliability_score,
            risk_score=s.risk_score,
            price_competitiveness=s.price_competitiveness,
            supplier_price=supplier_price,
            composite_score=round(composite, 3),
            is_domestic=s.is_domestic,
        ))
    results.sort(key=lambda x: x.composite_score, reverse=True)
    return results


@router.post("/{material_id}/refresh-prices")
async def refresh_prices(material_id: int, db: Session = Depends(get_db)):
    """Pull latest price data from FRED/Alpha Vantage for a material.

    Replaces existing price history with real API data when available.
    Returns count of records updated and the data source used.
    """
    from app.core.data_fetcher import fetch_price_history

    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")

    if not m.fred_series_id and not m.alpha_vantage_symbol:
        raise HTTPException(
            status_code=400,
            detail="No external data source configured for this material",
        )

    data = await fetch_price_history(m.fred_series_id, m.alpha_vantage_symbol, days=365)
    if not data:
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch data from external APIs. Check API keys in .env",
        )

    # Replace existing price history for this material
    db.query(PriceHistory).filter(PriceHistory.material_id == material_id).delete()

    for point in data:
        db.add(PriceHistory(
            material_id=material_id,
            date=point["date"],
            price=point["price"],
            source=point["source"],
        ))

    # Update current_price to most recent observation
    if data:
        latest = max(data, key=lambda d: d["date"])
        m.current_price = latest["price"]

    db.commit()

    return {
        "material_id": material_id,
        "records_updated": len(data),
        "source": data[0]["source"] if data else None,
        "latest_price": m.current_price,
    }


@router.post("/refresh-all")
async def refresh_all_prices(db: Session = Depends(get_db)):
    """Bulk refresh prices for all materials that have FRED or Alpha Vantage mappings.

    This is rate-limited by the APIs themselves (FRED: 120/min, Alpha Vantage: 5/min free tier).
    """
    from app.core.data_fetcher import fetch_price_history
    import asyncio

    materials = db.query(Material).filter(
        (Material.fred_series_id.isnot(None)) | (Material.alpha_vantage_symbol.isnot(None))
    ).all()

    results = {"updated": [], "failed": [], "skipped": []}

    for m in materials:
        try:
            data = await fetch_price_history(m.fred_series_id, m.alpha_vantage_symbol, days=365)
            if not data:
                results["failed"].append({"id": m.id, "name": m.name, "reason": "no data returned"})
                continue

            db.query(PriceHistory).filter(PriceHistory.material_id == m.id).delete()
            for point in data:
                db.add(PriceHistory(
                    material_id=m.id,
                    date=point["date"],
                    price=point["price"],
                    source=point["source"],
                ))

            latest = max(data, key=lambda d: d["date"])
            m.current_price = latest["price"]
            db.commit()

            results["updated"].append({
                "id": m.id,
                "name": m.name,
                "source": data[0]["source"],
                "records": len(data),
                "latest_price": m.current_price,
            })

            # Rate limit: Alpha Vantage free tier allows 5 req/min
            if m.alpha_vantage_symbol:
                await asyncio.sleep(12)

        except Exception as e:
            results["failed"].append({"id": m.id, "name": m.name, "reason": str(e)})

    return results
