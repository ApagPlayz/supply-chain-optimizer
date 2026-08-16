"""Add benchmark arm/scenario labels and selected-plan risk columns to optimization_runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06

Adds five columns used by the benchmark harness and disruption-scenario runs:
`scenario` (disruption scenario label), `arm` (benchmark arm label),
`plan_cascade_risk` (cascade risk of the selected sourcing plan, distinct from the
whole-network `cascade_risk_score`), `n_distinct_suppliers`, and `n_orders`.

`optimization_runs` is created by SQLAlchemy `create_all` (see app/main.py), not by
an earlier migration, so on a fresh DB the model already emits these columns and
there is nothing to add. The guards below make this a no-op in that case and only
add columns on pre-existing DBs that predate this change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ('scenario', sa.String(length=20)),
    ('plan_cascade_risk', sa.Float()),
    ('arm', sa.String(length=12)),
    ('n_distinct_suppliers', sa.Integer()),
    ('n_orders', sa.Integer()),
)


def _inspector(bind):
    inspector = sa.inspect(bind)
    try:
        inspector.clear_cache()
    except AttributeError:  # pragma: no cover - very old SQLAlchemy
        pass
    return inspector


def _has_table(bind, table: str) -> bool:
    return table in _inspector(bind).get_table_names()


def _has_column(bind, table: str, column: str) -> bool:
    """True only when the table exists AND carries the column.

    A False return is therefore ambiguous ("no table" vs "table but no column"),
    which is why every caller checks `_has_table` first. Without that check the
    guard `if not _has_column(...)` inverts on a missing table and tries to ALTER
    something that is not there.
    """
    inspector = _inspector(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    # No `optimization_runs` at all (fresh Alembic-only DB — the table is created
    # by create_all(), never by a migration) => nothing to alter.
    if not _has_table(bind, 'optimization_runs'):
        return
    for name, coltype in _NEW_COLUMNS:
        if not _has_column(bind, 'optimization_runs', name):
            op.add_column('optimization_runs', sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, 'optimization_runs'):
        return
    for name, _ in _NEW_COLUMNS:
        if _has_column(bind, 'optimization_runs', name):
            with op.batch_alter_table('optimization_runs') as batch_op:
                batch_op.drop_column(name)
