from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    category = Column(String(100), nullable=False, index=True)  # semiconductor, rare_earth, battery, metal, chemical, polymer
    subcategory = Column(String(100))
    unit = Column(String(50), nullable=False)          # kg, troy_oz, lb, each
    description = Column(Text)
    cas_number = Column(String(20))                     # Chemical Abstracts Service number
    current_price = Column(Float)                       # USD per unit
    price_unit = Column(String(50))                     # e.g. "$/kg", "$/troy oz"
    volatility_score = Column(Float, default=0.5)       # 0-1 price volatility
    supply_risk_score = Column(Float, default=0.5)      # 0-1 geopolitical/supply risk
    fred_series_id = Column(String(50))                 # FRED API series ID for price data
    alpha_vantage_symbol = Column(String(20))           # Alpha Vantage commodity symbol
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, nullable=False, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    price = Column(Float, nullable=False)
    source = Column(String(50))   # fred, alpha_vantage, eia, scraped


class PriceForecast(Base):
    __tablename__ = "price_forecasts"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, nullable=False, index=True)
    forecast_date = Column(DateTime(timezone=True), nullable=False)
    predicted_price = Column(Float, nullable=False)
    lower_ci = Column(Float)    # 80% confidence interval lower bound
    upper_ci = Column(Float)    # 80% confidence interval upper bound
    model_version = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
