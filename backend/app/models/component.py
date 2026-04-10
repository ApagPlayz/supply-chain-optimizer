from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Component(Base):
    """Electronic component from Nexar/Octopart dataset."""
    __tablename__ = "components"

    id = Column(Integer, primary_key=True, index=True)
    mpn = Column(String(100), nullable=False, index=True)  # Manufacturer Part Number
    manufacturer = Column(String(200), nullable=False, index=True)
    manufacturer_country = Column(String(100))
    category = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    datasheets = Column(JSON)  # list of URLs
    risk_score = Column(Float, default=0.0)  # 0-1 from Nexar analysis
    risk_factors = Column(JSON)  # e.g. ["chinese_origin", "single_source"]
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DistributorOffer(Base):
    """Real competitive price offer from a distributor for a component."""
    __tablename__ = "distributor_offers"

    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    distributor_id = Column(Integer, nullable=False, index=True)
    price = Column(Float)  # USD per unit (real from Nexar/Octopart)
    stock = Column(Integer, default=0)  # Real inventory count
    sku = Column(String(100))  # Distributor's SKU
    currency = Column(String(10), default="USD")
    moq = Column(Integer, default=1)  # Minimum order quantity
