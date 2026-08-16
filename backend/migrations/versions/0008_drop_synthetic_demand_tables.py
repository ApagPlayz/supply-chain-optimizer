"""Drop synthetic per-part demand tables (component_demand_history, component_forecasts)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-16

Why: `component_demand_history` was never observed demand. Its magnitude was
computed as (total_stock / 52) * a risk_score multiplier — inventory and risk
determining "demand", which is causally backwards — with only the week-to-week
SHAPE coming from the real Census M3 A34SNO series. `component_forecasts` held
per-part Prophet fits on that fabricated series, forecasting a 12-week window
that ended 17 months ago with no actuals ever collected against it, so it is
unscoreable in principle. Both tables, their ORM models (app/models/forecast.py)
and the `/forecasts` API (app/api/forecasts.py) and seed script
(seeds/train_forecasts.py) that produced/served them have been removed. The two
REAL demand backtests (seeds/run_forecast_backtest.py against Census M3 A34SNO,
seeds/run_carparts_backtest.py against Monash Car Parts) are unaffected — they
never depended on these tables.

`component_demand_history` and `component_forecasts` are created by SQLAlchemy
`Base.metadata.create_all()` (see app/main.py) whenever a fresh DB is built. Now
that the ORM models are deleted, `create_all()` no longer emits them, so on a
fresh install these tables never exist. The `_has_table` guard below makes
`upgrade()` a no-op in that case and only drops the tables (and their indexes)
on pre-existing DBs that still carry them from before this change. `downgrade()`
is guarded symmetrically so it does not try to recreate a table that is somehow
already present.

Index names are NOT assumed. The tables in the shipped DB were built by
`create_all()` from the ORM models, so their indexes are named
`ix_component_demand_history_week_date` / `ix_component_demand_history_id` / ...,
whereas 0002_forecast_tables.py names them `ix_demand_history_week_date` / ...
Hard-coding 0002's names made this migration die with
`no such index: ix_demand_history_week_date` on the real DB — and because SQLite
DDL runs outside the transaction, the failure HALF-APPLIED: `component_forecasts`
was already dropped, `component_demand_history` survived, and the version table
stayed on 0007, leaving the DB permanently wedged with the data already gone.
So `upgrade()` now discovers whatever indexes each table actually has and drops
those, tolerating either naming (and any other). Every step is existence-checked,
so a partially-applied DB re-runs cleanly to completion.

Drop order (child table `component_forecasts` first, then
`component_demand_history`) and the column definitions in `downgrade()` mirror
0002_forecast_tables.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector(bind):
    inspector = sa.inspect(bind)
    try:
        inspector.clear_cache()
    except AttributeError:  # pragma: no cover - very old SQLAlchemy
        pass
    return inspector


def _has_table(bind, table: str) -> bool:
    return table in _inspector(bind).get_table_names()


def _index_names(bind, table: str):
    """Names of the indexes that actually exist on `table`, whatever they are.

    Never assume a name: the same logical index is called
    `ix_demand_history_week_date` if 0002 built the table and
    `ix_component_demand_history_week_date` if `create_all()` did. Backend-managed
    implicit indexes (SQLite's `sqlite_autoindex_*`) are excluded — they are
    dropped with the table and cannot be dropped on their own.
    """
    if not _has_table(bind, table):
        return []
    names = []
    for index in _inspector(bind).get_indexes(table):
        name = index.get('name')
        if name and not name.startswith('sqlite_'):
            names.append(name)
    return names


def _drop_table_if_present(table: str) -> None:
    bind = op.get_bind()
    if not _has_table(bind, table):
        return
    for name in _index_names(bind, table):
        op.drop_index(name, table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    # Child table first, then the parent — and each step is a no-op when the
    # object is already gone, so a half-applied run resumes cleanly.
    _drop_table_if_present('component_forecasts')
    _drop_table_if_present('component_demand_history')


def downgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, 'component_demand_history'):
        op.create_table(
            'component_demand_history',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('component_id', sa.Integer(), nullable=False),
            sa.Column('week_date', sa.DateTime(timezone=True), nullable=False),
            sa.Column('demand_units', sa.Float(), nullable=False),
        )
        op.create_index('ix_demand_history_component_id', 'component_demand_history', ['component_id'])
        op.create_index('ix_demand_history_week_date', 'component_demand_history', ['week_date'])

    if not _has_table(bind, 'component_forecasts'):
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
