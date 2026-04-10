from sqlalchemy import Column, Float, Integer, String, Text
from app.core.database import Base


class CrossDockHub(Base):
    """Real US freight hub used as cross-dock consolidation candidate."""
    __tablename__ = "cross_dock_hubs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    operator = Column(String(100))
    hub_type = Column(String(50))
    city = Column(String(100))
    state = Column(String(10))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    annual_throughput_desc = Column(Text)
    source_citation = Column(String(300))
