"""
Append-only audit row for a single (BOM × strategy × graph_aware) optimizer invocation.

BENCH-01 (Phase 4). Benchmark invocation produces 20 rows per run_id (10 BOMs × 2 graph_aware).
D-09: run_id + timestamp keyed; /benchmark/summary defaults to latest run_id.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id = Column(Integer, primary_key=True, index=True)

    # Run grouping (D-09)
    run_id = Column(Integer, nullable=False, index=True)
    run_tag = Column(String(50), nullable=False, default="benchmark")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Input identity
    bom_name = Column(String(100), nullable=False, index=True)
    bom_items_json = Column(JSON, nullable=False)

    # Strategy + flag (BENCH-01 + D-02)
    strategy = Column(String(20), nullable=False, default="balanced")
    graph_aware = Column(Boolean, nullable=False, index=True)

    # Pre-projected scalars (BENCH-01 explicit requirement)
    total_cost_usd = Column(Float, nullable=False)
    total_component_cost_usd = Column(Float)
    total_transport_cost_usd = Column(Float)
    eta_p10_days = Column(Float)
    eta_p50_days = Column(Float, nullable=False)
    eta_p90_days = Column(Float)
    co2_kg = Column(Float, nullable=False)
    cascade_risk_score = Column(Float, nullable=False)

    # Full Monte Carlo payload for dashboard distribution plot (BENCH-04)
    monte_carlo_samples = Column(JSON)   # list[float], trimmed to 200 points
    mc_evar_95 = Column(Float)

    # Feed status at run time (D-10 static-fallback mode tag)
    feeds_available = Column(JSON)        # {"gpr": bool, "acled": bool, ...}

    # Selected distributors snapshot — for "Where Graph-Aware Loses" narrative
    selected_distributor_ids = Column(JSON)
    selected_distributor_names = Column(JSON)
