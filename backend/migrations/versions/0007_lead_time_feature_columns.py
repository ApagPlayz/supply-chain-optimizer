"""Add lead-time feature columns (part-level DigiKey catalog attributes)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-15

The lead-time model's observed panel
(`backend/seeds/data/lead_time_panel/observed_lead_times.csv`) carries seven more
DigiKey catalog columns that the model could already TRAIN on but could not
SERVE, because `Component` had no columns for them: parameter_count,
package_case, htsus_code, rohs_status, dk_unit_price, max_break_qty,
price_break_count. Same situation migration 0006 fixed for the first batch of
catalog attributes — without a place to persist them, these features would be
dead weight at prediction time.

All seven land on `Component`, not `DistributorOffer`, even though
`max_break_qty` / `price_break_count` / `digikey_unit_price` look offer-shaped
(they come from a distributor pricing table). The model predicts a part's
FACTORY lead time — a property of the part, not of which distributor you buy
from — and the observed panel has exactly one DigiKey row per part. Storing
them part-level makes them resolvable for every offer of that part, instead of
NULL on every non-DigiKey offer.

`digikey_unit_price` specifically exists to remove a train/serve skew: the
model trains on the panel's `dk_unit_price`, but was serving
`DistributorOffer.price` — a possibly different vendor's price for the same
part.

Columns are nullable on purpose. A NULL means "DigiKey returned no value for
this part" — a real absence, not a zero or empty string to impute.

`components` is created by SQLAlchemy `create_all` (see app/main.py), not by
an earlier migration — same situation as 0006 — so on a fresh DB the model
already emits these columns and there is nothing to add. The guard below makes
this a no-op in that case and only adds columns on pre-existing DBs that
predate this change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, type) — every one read straight off the DigiKey v4 product
# response / observed panel by app/ml/lead_time_collector.py.
_NEW_COLUMNS = (
    ('components', 'parameter_count', sa.Integer()),        # parameter_count
    ('components', 'package_case', sa.String(length=200)),  # package_case
    ('components', 'htsus_code', sa.String(length=50)),      # htsus_code
    ('components', 'rohs_status', sa.String(length=100)),    # rohs_status
    ('components', 'digikey_unit_price', sa.Float()),        # dk_unit_price
    ('components', 'max_break_qty', sa.Integer()),           # max_break_qty
    ('components', 'price_break_count', sa.Integer()),       # price_break_count
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

    A False return is ambiguous ("no table" vs "table but no column"), so callers
    must check `_has_table` first — otherwise `if not _has_column(...)` inverts on
    a missing table and tries to ALTER something that is not there.
    """
    inspector = _inspector(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table, name, coltype in _NEW_COLUMNS:
        # Missing table (fresh Alembic-only DB — `components` is created by
        # create_all(), never by a migration) => skip, don't ALTER.
        if not _has_table(bind, table):
            continue
        if not _has_column(bind, table, name):
            op.add_column(table, sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    for table in ('components',):
        if not _has_table(bind, table):
            continue
        cols = [n for t, n, _ in _NEW_COLUMNS
                if t == table and _has_column(bind, table, n)]
        if not cols:
            continue
        with op.batch_alter_table(table) as batch_op:
            for name in cols:
                batch_op.drop_column(name)
