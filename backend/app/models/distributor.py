from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from app.core.database import Base


class Distributor(Base):
    """Real electronic components distributor with warehouse location."""
    __tablename__ = "distributors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    city = Column(String(100))
    state = Column(String(50))
    country = Column(String(100), default="USA")
    is_domestic = Column(Boolean, default=True)
    total_offers = Column(Integer, default=0)  # How many components they carry
    total_stock = Column(Integer, default=0)  # Aggregate inventory
    description = Column(Text)
