"""Scenario cache table for Phase 6 resilience scenarios

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-05

Adds:
  - scenario_cache (caches simulation results with 1h TTL)
    Columns: id, scenario_type, cache_key (unique), result_json, created_at, expires_at, accessed_at

Phase 6 (RESIL-01, RESIL-02, RESIL-03). Mirrors 0001/0002 style.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scenario_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scenario_type', sa.String(50), nullable=False),
        sa.Column('cache_key', sa.String(512), nullable=False, unique=True),
        sa.Column('result_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accessed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_scenario_cache_scenario_type', 'scenario_cache', ['scenario_type'])
    op.create_index('ix_scenario_cache_cache_key', 'scenario_cache', ['cache_key'], unique=True)
    op.create_index('ix_scenario_cache_created_at', 'scenario_cache', ['created_at'])
    op.create_index('ix_scenario_cache_expires_at', 'scenario_cache', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_scenario_cache_expires_at', table_name='scenario_cache')
    op.drop_index('ix_scenario_cache_created_at', table_name='scenario_cache')
    op.drop_index('ix_scenario_cache_cache_key', table_name='scenario_cache')
    op.drop_index('ix_scenario_cache_scenario_type', table_name='scenario_cache')
    op.drop_table('scenario_cache')
