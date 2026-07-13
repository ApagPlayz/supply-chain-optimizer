"""SQLAlchemy ORM models for scenario caching (Phase 6).

ScenarioCache table:
  - Caches results from scenario simulation endpoints (distributor-failure, geopolitical-risk, delivery-target)
  - Keys: scenario_type, cache_key (deterministic SHA256 hash of params)
  - TTL: 1 hour (expires_at column for cleanup)
  - Tracks: created_at (creation time), accessed_at (last read time for analytics)
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ScenarioCache(Base):
    """Cache for scenario simulation results with 1-hour TTL."""
    __tablename__ = "scenario_cache"

    id = Column(Integer, primary_key=True, index=True)
    scenario_type = Column(String(50), nullable=False, index=True)  # e.g., "distributor-failure"
    cache_key = Column(String(512), nullable=False, unique=True, index=True)  # SHA256 hash of params
    result_json = Column(Text, nullable=False)  # JSON-serialized response
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)  # For cleanup queries
    accessed_at = Column(DateTime(timezone=True), server_default=func.now())  # Last read timestamp
