"""
Forecasts API — Phase 5 (FORE-03).

Single bulk endpoint:
  GET /forecasts/all  — returns all 791 component forecasts in one response.

The frontend SchedulerPage loads this once on mount and renders an inline
sparkline + stock-out badge per component card. Per-component endpoints would
trigger 791 HTTP requests on page load (Anti-Pattern in RESEARCH.md).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func as sqla_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.component import DistributorOffer
from app.models.forecast import ComponentForecast

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ForecastPoint(BaseModel):
    """One weekly forecast point."""
    forecast_date: str                 # ISO 8601 — e.g. "2026-05-04T00:00:00+00:00"
    predicted_demand: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None


class ComponentForecastResponse(BaseModel):
    """Per-component forecast bundle delivered to the frontend."""
    component_id: int
    forecast_points: List[ForecastPoint]            # exactly 12 entries (forecast horizon)
    weeks_until_stockout: Optional[float] = None    # None = no demand; 0.0 = already out; >12 = healthy


# ── Stock-out formula (Pattern 6 from RESEARCH.md) ────────────────────────────

def compute_weeks_until_stockout(
    total_stock: int,
    last_4_forecasts: List[float],
) -> Optional[float]:
    """
    Estimate weeks until total stock is exhausted given recent demand trajectory.

    Returns:
      - None if predicted demand is zero (infinite supply / no signal).
      - 0.0 if total_stock is zero AND demand is positive (already out).
      - Otherwise: total_stock / mean(max(0, last_4_forecasts)).

    Negative yhat values from Prophet (noise can push yhat_lower below zero) are
    clipped to 0 before averaging — they are not real signals.
    """
    if not last_4_forecasts:
        return None
    clipped = [max(0.0, v) for v in last_4_forecasts]
    avg = sum(clipped) / len(clipped)
    if avg <= 0.0:
        return None
    if total_stock <= 0:
        return 0.0
    return total_stock / avg


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/all", response_model=List[ComponentForecastResponse])
def get_all_forecasts(db: Session = Depends(get_db)) -> List[ComponentForecastResponse]:
    """
    Returns all stored forecasts grouped by component_id.

    Two SQL queries total:
      1. Pull every ComponentForecast row, ordered by component_id then forecast_date.
      2. Aggregate SUM(DistributorOffer.stock) per component_id for the stockout calc.

    If component_forecasts is empty (training script never run), returns []
    rather than raising — the frontend renders cards without sparklines.
    """
    # Query 1: all forecast rows in deterministic order.
    rows = (
        db.query(ComponentForecast)
        .order_by(ComponentForecast.component_id, ComponentForecast.forecast_date)
        .all()
    )

    # Query 2: total stock per component.
    stock_rows = (
        db.query(
            DistributorOffer.component_id,
            sqla_func.coalesce(sqla_func.sum(DistributorOffer.stock), 0).label("total_stock"),
        )
        .group_by(DistributorOffer.component_id)
        .all()
    )
    stock_by_component: Dict[int, int] = {r.component_id: int(r.total_stock or 0) for r in stock_rows}

    # Group forecast rows by component_id.
    grouped: Dict[int, List[ForecastPoint]] = defaultdict(list)
    for row in rows:
        grouped[row.component_id].append(ForecastPoint(
            forecast_date=row.forecast_date.isoformat() if row.forecast_date else "",
            predicted_demand=float(row.predicted_demand),
            lower_bound=float(row.lower_bound) if row.lower_bound is not None else None,
            upper_bound=float(row.upper_bound) if row.upper_bound is not None else None,
        ))

    # Build response.
    out: List[ComponentForecastResponse] = []
    for component_id, points in grouped.items():
        # Last 4 forecast yhat values feed the stockout formula (RESEARCH.md Pattern 6).
        last_4 = [p.predicted_demand for p in points[-4:]]
        weeks = compute_weeks_until_stockout(
            total_stock=stock_by_component.get(component_id, 0),
            last_4_forecasts=last_4,
        )
        out.append(ComponentForecastResponse(
            component_id=component_id,
            forecast_points=points,
            weeks_until_stockout=weeks,
        ))

    # Sort by component_id ascending for deterministic responses (matches DB order).
    out.sort(key=lambda r: r.component_id)
    return out
