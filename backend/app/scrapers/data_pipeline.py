"""
Celery tasks for real-time data pipeline:
- FRED API: commodity prices & PPI
- Alpha Vantage: metals spot prices (Cu, Al, Au, Ag)
- EIA API: energy costs
- Graceful fallback when API keys are missing
"""
import logging
from datetime import datetime
from typing import Optional

import requests

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.material import Material, PriceHistory

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
EIA_BASE = "https://api.eia.gov/v2/electricity/retail-sales/data"
AV_BASE = "https://www.alphavantage.co/query"


def _upsert_price(db, material_id: int, date: datetime, price: float, source: str):
    """Insert price record; skip duplicates by (material_id, date, source)."""
    existing = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.material_id == material_id,
            PriceHistory.date == date,
            PriceHistory.source == source,
        )
        .first()
    )
    if not existing:
        db.add(PriceHistory(material_id=material_id, date=date, price=price, source=source))


@celery_app.task(name="pipeline.fetch_fred_prices")
def fetch_fred_prices():
    """Pull commodity price series from FRED API and store in price_history."""
    if not settings.FRED_API_KEY:
        logger.warning("FRED_API_KEY not set — skipping FRED price pull")
        return {"status": "skipped", "reason": "no API key"}

    db = SessionLocal()
    updated = 0
    try:
        # Map FRED series IDs → material categories for lookup
        series_targets = [
            ("PCOPPUSDM", "Copper Cathode (LME Grade A)"),
            ("PALUMUSDM", "Aluminum (99.7% primary ingot)"),
            ("PGOLDUSDM", "Gold (99.99% fine)"),
            ("PSILVUSDM", "Silver (99.9% fine)"),
        ]
        for series_id, material_name in series_targets:
            mat = db.query(Material).filter(Material.name == material_name).first()
            if not mat:
                continue
            resp = requests.get(FRED_BASE, params={
                "series_id": series_id,
                "api_key": settings.FRED_API_KEY,
                "file_type": "json",
                "observation_start": "2023-01-01",
                "limit": 200,
            }, timeout=10)
            if resp.status_code != 200:
                logger.error(f"FRED error for {series_id}: {resp.status_code}")
                continue
            data = resp.json()
            for obs in data.get("observations", []):
                if obs.get("value") == ".":
                    continue
                try:
                    price = float(obs["value"])
                    date = datetime.strptime(obs["date"], "%Y-%m-%d")
                    _upsert_price(db, mat.id, date, price, "fred")
                    updated += 1
                except (ValueError, KeyError):
                    pass
            db.commit()
    finally:
        db.close()
    return {"status": "ok", "rows_updated": updated}


@celery_app.task(name="pipeline.fetch_alpha_vantage_prices")
def fetch_alpha_vantage_prices():
    """Pull metals prices from Alpha Vantage commodity data."""
    if not settings.ALPHA_VANTAGE_API_KEY:
        logger.warning("ALPHA_VANTAGE_API_KEY not set — skipping")
        return {"status": "skipped", "reason": "no API key"}

    db = SessionLocal()
    updated = 0
    try:
        # Alpha Vantage commodity symbols
        av_targets = [
            ("COPPER", "Copper Cathode (LME Grade A)"),
            ("ALUMINUM", "Aluminum (99.7% primary ingot)"),
        ]
        for symbol, material_name in av_targets:
            mat = db.query(Material).filter(Material.name == material_name).first()
            if not mat:
                continue
            resp = requests.get(AV_BASE, params={
                "function": "COMMODITY_EXCHANGE_RATE",  # uses GLOBAL_QUOTE for equities
                "symbol": symbol,
                "apikey": settings.ALPHA_VANTAGE_API_KEY,
            }, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            # Try commodity monthly series
            ts = data.get("data", [])
            for row in ts[:90]:
                try:
                    price = float(row["value"])
                    date = datetime.strptime(row["date"], "%Y-%m-%d")
                    _upsert_price(db, mat.id, date, price, "alpha_vantage")
                    updated += 1
                except (ValueError, KeyError, TypeError):
                    pass
            db.commit()
    finally:
        db.close()
    return {"status": "ok", "rows_updated": updated}


@celery_app.task(name="pipeline.refresh_material_prices")
def refresh_material_prices():
    """Update current_price for all materials from latest price_history entry."""
    db = SessionLocal()
    updated = 0
    try:
        materials = db.query(Material).all()
        for mat in materials:
            latest = (
                db.query(PriceHistory)
                .filter(PriceHistory.material_id == mat.id)
                .order_by(PriceHistory.date.desc())
                .first()
            )
            if latest and latest.price and latest.price != mat.current_price:
                mat.current_price = latest.price
                updated += 1
        db.commit()
    finally:
        db.close()
    return {"status": "ok", "materials_updated": updated}


@celery_app.task(name="pipeline.run_full_pipeline")
def run_full_pipeline():
    """Orchestrate all data pulls in sequence."""
    results = {}
    results["fred"] = fetch_fred_prices()
    results["alpha_vantage"] = fetch_alpha_vantage_prices()
    results["price_refresh"] = refresh_material_prices()
    return results
