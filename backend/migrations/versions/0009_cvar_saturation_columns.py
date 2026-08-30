"""Persist the measures that keep discriminating after CVaR-95 saturates

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-28

OUTSTANDING_WORK.md item 13. `mc_cvar_95` is a mean over the worst-5% tail of
`cost_inflation = 1 + unfulfillable_share * EMERGENCY_COST_PREMIUM`, which is
bounded above by `1 + premium` (1.15 at the default). Under `stress_factor=3`
most benchmark plans sit ON that ceiling, so two very differently exposed arms
print the identical 1.15 and a reader has no way to tell a ceiling from a
finding of equal risk.

`graph/simulation.run_monte_carlo` has computed `p_shortfall`,
`p_total_shortfall`, `cvar_95_ceiling` and `cvar_95_saturated` since the
2026-08-28 sweep, but nothing persisted them, so the 18 published CVaR cells
still tied unflagged. This adds the four columns that carry them, so
`/benchmark/summary` can serve the saturation flag beside every CVaR figure.

`optimization_runs` is created by SQLAlchemy `create_all` (see app/main.py), not
by an earlier migration, so on a fresh DB the model already emits these columns
and there is nothing to add. The guards below make this a no-op in that case and
only add columns on pre-existing DBs that predate this change. Same shape as
0005, which added the previous five columns to this table.

Existing rows keep NULL: they were written by a run that never measured these,
and back-filling them with a guessed value would be fabrication. A NULL here
means "this run predates the measurement", and the API is written to say so
rather than to print a zero.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ('mc_p_shortfall', sa.Float()),
    ('mc_p_total_shortfall', sa.Float()),
    ('mc_cvar_95_ceiling', sa.Float()),
    ('mc_cvar_95_saturated', sa.Boolean()),
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
    which is why every caller checks `_has_table` first.
    """
    inspector = _inspector(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
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
