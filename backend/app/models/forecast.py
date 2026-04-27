"""SQLAlchemy ORM models for Prophet demand forecasting (Phase 5).

Two tables:
  - component_demand_history: 52 weekly synthetic drawdown rows per component
    (input training data for Prophet; persisted per CONTEXT.md D-05).
  - component_forecasts: 12 weekly Prophet forecast rows per component
    (yhat / yhat_lower / yhat_upper from .predict()).
"""
from sqlalchemy import Column, Integer, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ComponentDemandHistory(Base):
    """52-row weekly synthetic drawdown series, one row per (component_id, week_date)."""
    __tablename__ = "component_demand_history"

    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    week_date = Column(DateTime(timezone=True), nullable=False, index=True)
    demand_units = Column(Float, nullable=False)


class ComponentForecast(Base):
    """12-row weekly Prophet forecast: predicted_demand + 80% CI bounds."""
    __tablename__ = "component_forecasts"

    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    forecast_date = Column(DateTime(timezone=True), nullable=False)
    predicted_demand = Column(Float, nullable=False)
    lower_bound = Column(Float)   # yhat_lower from Prophet predict() — nullable defensively
    upper_bound = Column(Float)   # yhat_upper from Prophet predict()
    created_at = Column(DateTime(timezone=True), server_default=func.now())
