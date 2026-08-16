"""Forecast tables for Prophet demand forecasting

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-27

Adds:
  - component_demand_history (52 weekly drawdown rows per component, training input)
  - component_forecasts (12 weekly Prophet forecast rows per component, predict output)

Phase 5 (FORE-01). Mirrors 0001_initial_schema.py style.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector(bind):
    inspector = sa.inspect(bind)
    try:
        inspector.clear_cache()
    except AttributeError:  # pragma: no cover - very old SQLAlchemy
        pass
    return inspector


def _create_table(name: str, *columns, **kw) -> None:
    """`op.create_table` that no-ops when the table is already present.

    Every table the product actually uses is built by
    `Base.metadata.create_all()` (see app/main.py), not by Alembic, so some of
    these names can already exist when the chain runs. An unguarded CREATE dies
    with `table <name> already exists` and blocks every later revision.
    """
    bind = op.get_bind()
    if name in _inspector(bind).get_table_names():
        return
    op.create_table(name, *columns, **kw)


def _create_index(name: str, table: str, columns, **kw) -> None:
    """`op.create_index` that no-ops when the index is redundant or impossible.

    Skips when the table is absent, when the name is already taken, and when an
    equivalent index (same column list) already exists under a DIFFERENT name --
    which is exactly the case for a `create_all()`-built DB, whose index names
    follow the ORM convention rather than the names used here.
    """
    bind = op.get_bind()
    inspector = _inspector(bind)
    if table not in inspector.get_table_names():
        return
    existing = inspector.get_indexes(table)
    if any(ix.get('name') == name for ix in existing):
        return
    if any(list(ix.get('column_names') or []) == list(columns) for ix in existing):
        return
    op.create_index(name, table, columns, **kw)


def _drop_index(name: str, table: str) -> None:
    """`op.drop_index` that no-ops when the table or the index is already gone."""
    bind = op.get_bind()
    inspector = _inspector(bind)
    if table not in inspector.get_table_names():
        return
    if any(ix.get('name') == name for ix in inspector.get_indexes(table)):
        op.drop_index(name, table_name=table)


def _drop_table(name: str) -> None:
    """`op.drop_table` that no-ops when the table is already gone."""
    bind = op.get_bind()
    if name in _inspector(bind).get_table_names():
        op.drop_table(name)


def upgrade() -> None:
    _create_table(
        'component_demand_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('component_id', sa.Integer(), nullable=False),
        sa.Column('week_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('demand_units', sa.Float(), nullable=False),
    )
    _create_index('ix_demand_history_component_id', 'component_demand_history', ['component_id'])
    _create_index('ix_demand_history_week_date', 'component_demand_history', ['week_date'])

    _create_table(
        'component_forecasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('component_id', sa.Integer(), nullable=False),
        sa.Column('forecast_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('predicted_demand', sa.Float(), nullable=False),
        sa.Column('lower_bound', sa.Float()),
        sa.Column('upper_bound', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_index('ix_component_forecasts_component_id', 'component_forecasts', ['component_id'])


def downgrade() -> None:
    _drop_index('ix_component_forecasts_component_id', 'component_forecasts')
    _drop_table('component_forecasts')
    _drop_index('ix_demand_history_week_date', 'component_demand_history')
    _drop_index('ix_demand_history_component_id', 'component_demand_history')
    _drop_table('component_demand_history')
