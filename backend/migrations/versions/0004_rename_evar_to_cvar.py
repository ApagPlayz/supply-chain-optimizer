"""Rename mc_evar_95 -> mc_cvar_95 on optimization_runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-06

The Monte Carlo tail metric was mislabeled "EVaR" (Entropic VaR). It is actually
CVaR / Expected Shortfall: the mean cost multiplier over the worst-5% scenarios.
This renames the stored column to match the corrected terminology used across the
API and UI. Data is preserved (pure column rename).

`optimization_runs` is created by SQLAlchemy `create_all` (see app/main.py), not by
an earlier migration, so on a fresh DB the model already emits the corrected column
name and there is nothing to rename. The guard below makes this a no-op in that case
and only renames on pre-existing DBs that still carry the old column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, 'optimization_runs', 'mc_evar_95'):
        with op.batch_alter_table('optimization_runs') as batch_op:
            batch_op.alter_column('mc_evar_95', new_column_name='mc_cvar_95')


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, 'optimization_runs', 'mc_cvar_95'):
        with op.batch_alter_table('optimization_runs') as batch_op:
            batch_op.alter_column('mc_cvar_95', new_column_name='mc_evar_95')
