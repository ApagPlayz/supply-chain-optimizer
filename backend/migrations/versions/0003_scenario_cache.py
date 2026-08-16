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
        'scenario_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scenario_type', sa.String(50), nullable=False),
        sa.Column('cache_key', sa.String(512), nullable=False, unique=True),
        sa.Column('result_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accessed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_index('ix_scenario_cache_scenario_type', 'scenario_cache', ['scenario_type'])
    _create_index('ix_scenario_cache_cache_key', 'scenario_cache', ['cache_key'], unique=True)
    _create_index('ix_scenario_cache_created_at', 'scenario_cache', ['created_at'])
    _create_index('ix_scenario_cache_expires_at', 'scenario_cache', ['expires_at'])


def downgrade() -> None:
    _drop_index('ix_scenario_cache_expires_at', 'scenario_cache')
    _drop_index('ix_scenario_cache_created_at', 'scenario_cache')
    _drop_index('ix_scenario_cache_cache_key', 'scenario_cache')
    _drop_index('ix_scenario_cache_scenario_type', 'scenario_cache')
    _drop_table('scenario_cache')
