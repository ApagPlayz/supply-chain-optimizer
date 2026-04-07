from sqlalchemy import Column, Integer, String, Float, Text, Boolean
from app.core.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    hub_id = Column(Integer, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    city = Column(String(100))
    state = Column(String(2))
    materials_supplied = Column(Text)        # comma-separated material IDs
    lead_time_days = Column(Integer, default=7)
    reliability_score = Column(Float, default=0.8)   # 0-1
    risk_score = Column(Float, default=0.3)           # 0-1 composite risk
    financial_health = Column(Float, default=0.7)     # 0-1
    geo_risk = Column(Float, default=0.2)             # 0-1 geopolitical risk
    weather_risk = Column(Float, default=0.2)         # 0-1 weather exposure
    price_competitiveness = Column(Float, default=0.7) # 0-1 (1 = cheapest)
    annual_capacity_kg = Column(Float)
    certifications = Column(Text)             # ISO9001, RoHS, REACH etc
    is_domestic = Column(Boolean, default=True)
    description = Column(Text)
