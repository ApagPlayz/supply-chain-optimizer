"""
Regression tests for OptimizationRun ORM model.

Guards BENCH-01 (Phase 4). Confirms:
  - Column schema matches the plan contract (exactly 19 columns)
  - Base.metadata.create_all registers the "optimization_runs" table
  - Nullable constraints fire on missing required scalars
  - The model is exported from app.models for clean imports

See .planning/phases/04-benchmark-dashboard/04-RESEARCH.md §Pattern 1.
"""
from __future__ import annotations

import pytest
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
)
from sqlalchemy.exc import IntegrityError

from app.models import OptimizationRun


# ── Column type lookup built from the SQLAlchemy column definitions ──────────
_EXPECTED_COLUMNS = {
    "id": Integer,
    "run_id": Integer,
    "run_tag": String,
    "created_at": DateTime,
    "bom_name": String,
    "bom_items_json": JSON,
    "strategy": String,
    "graph_aware": Boolean,
    "total_cost_usd": Float,
    "total_component_cost_usd": Float,
    "total_transport_cost_usd": Float,
    "eta_p10_days": Float,
    "eta_p50_days": Float,
    "eta_p90_days": Float,
    "co2_kg": Float,
    "cascade_risk_score": Float,
    "monte_carlo_samples": JSON,
    "mc_evar_95": Float,
    "feeds_available": JSON,
    "selected_distributor_ids": JSON,
    "selected_distributor_names": JSON,
}

_NON_NULL_COLUMNS = {
    "run_id",
    "run_tag",
    "bom_name",
    "bom_items_json",
    "strategy",
    "graph_aware",
    "total_cost_usd",
    "eta_p50_days",
    "co2_kg",
    "cascade_risk_score",
}


def test_columns_present():
    """Every expected column exists on the ORM model with the right SQL type family."""
    actual = {c.name: c for c in OptimizationRun.__table__.columns}

    # Every expected column present
    for name, expected_type in _EXPECTED_COLUMNS.items():
        assert name in actual, f"missing column: {name}"
        col = actual[name]
        assert isinstance(col.type, expected_type), (
            f"column {name} expected {expected_type}, got {type(col.type)}"
        )

    # Nullable constraints enforced on the right columns
    for name in _NON_NULL_COLUMNS:
        assert actual[name].nullable is False, (
            f"column {name} should be non-nullable"
        )


def test_tablename():
    assert OptimizationRun.__tablename__ == "optimization_runs"


def test_append_insert(db_session):
    """After Base.metadata.create_all, inserting a minimal row and re-querying yields it back."""
    row = OptimizationRun(
        run_id=1,
        run_tag="benchmark",
        bom_name="iot_sensor_node",
        bom_items_json=[{"component_id": 1, "quantity": 1}],
        strategy="balanced",
        graph_aware=False,
        total_cost_usd=100.0,
        eta_p50_days=5.0,
        co2_kg=2.5,
        cascade_risk_score=0.1,
    )
    db_session.add(row)
    db_session.commit()

    rows = db_session.query(OptimizationRun).all()
    assert len(rows) == 1
    got = rows[0]
    assert got.run_id == 1
    assert got.run_tag == "benchmark"
    assert got.bom_name == "iot_sensor_node"
    assert got.graph_aware is False
    assert got.total_cost_usd == 100.0
    assert got.eta_p50_days == 5.0
    assert got.co2_kg == 2.5
    assert got.cascade_risk_score == 0.1
    assert got.bom_items_json == [{"component_id": 1, "quantity": 1}]


def test_nullable_enforced(db_session):
    """Insert with total_cost_usd=None must raise IntegrityError (NOT NULL guard)."""
    bad = OptimizationRun(
        run_id=2,
        run_tag="benchmark",
        bom_name="pcb_power_supply",
        bom_items_json=[{"component_id": 1, "quantity": 1}],
        strategy="balanced",
        graph_aware=True,
        total_cost_usd=None,     # ← violates nullable=False
        eta_p50_days=3.0,
        co2_kg=1.0,
        cascade_risk_score=0.05,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_exported_from_init():
    """`from app.models import OptimizationRun` must work without ImportError."""
    from app.models import OptimizationRun as OR
    assert OR is OptimizationRun
    assert OR.__tablename__ == "optimization_runs"
