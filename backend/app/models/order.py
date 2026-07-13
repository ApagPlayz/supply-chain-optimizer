from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    distributor_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float)  # Real price from distributor offer
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="pending")   # pending, optimized, confirmed
    total_cost = Column(Float)
    total_co2e_kg = Column(Float)                    # kg CO2 equivalent
    eta_days = Column(Float)
    eta_lower_ci = Column(Float)                     # Monte Carlo 10th percentile
    eta_upper_ci = Column(Float)                     # Monte Carlo 90th percentile
    optimized_route = Column(JSON)                   # VRP solution JSON
    monte_carlo_results = Column(JSON)               # distribution data
    items = Column(JSON)                             # snapshot of cart items
    created_at = Column(DateTime(timezone=True), server_default=func.now())
