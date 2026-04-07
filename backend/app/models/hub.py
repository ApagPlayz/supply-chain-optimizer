from sqlalchemy import Column, Integer, String, Float, Text, ARRAY
from app.core.database import Base


class ProductionHub(Base):
    __tablename__ = "production_hubs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    city = Column(String(100), nullable=False)
    state = Column(String(2), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    hub_type = Column(String(100))          # e.g. "semiconductor", "rare_earth", "battery"
    specialization = Column(Text)           # comma-separated primary materials
    description = Column(Text)
    active_suppliers = Column(Integer, default=0)
    risk_index = Column(Float, default=0.0) # 0-1 composite risk score
