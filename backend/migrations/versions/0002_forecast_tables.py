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


def upgrade() -> None:
    op.create_table(
        'component_demand_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('component_id', sa.Integer(), nullable=False),
        sa.Column('week_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('demand_units', sa.Float(), nullable=False),
    )
    op.create_index('ix_demand_history_component_id', 'component_demand_history', ['component_id'])
    op.create_index('ix_demand_history_week_date', 'component_demand_history', ['week_date'])

    op.create_table(
        'component_forecasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('component_id', sa.Integer(), nullable=False),
        sa.Column('forecast_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('predicted_demand', sa.Float(), nullable=False),
        sa.Column('lower_bound', sa.Float()),
        sa.Column('upper_bound', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_component_forecasts_component_id', 'component_forecasts', ['component_id'])


def downgrade() -> None:
    op.drop_index('ix_component_forecasts_component_id', table_name='component_forecasts')
    op.drop_table('component_forecasts')
    op.drop_index('ix_demand_history_week_date', table_name='component_demand_history')
    op.drop_index('ix_demand_history_component_id', table_name='component_demand_history')
    op.drop_table('component_demand_history')
