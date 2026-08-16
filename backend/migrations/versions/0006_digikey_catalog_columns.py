"""Add DigiKey catalog attributes to components and distributor_offers

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15

The lead-time model trains on the observed panel
(`backend/seeds/data/lead_time_panel/observed_lead_times.csv`), which now carries
the part-level attributes DigiKey returns — lifecycle status, normally-stocked
flag, packaging, pack size. Without somewhere to persist them, those features
could be trained on but never *served*, because `Component` / `DistributorOffer`
had no columns for them. This migration adds exactly the fields the DigiKey
Product Information v4 response genuinely returns. Nothing here is derived.

Columns are nullable on purpose. A NULL means "DigiKey returned no value for this
part / this offer is not a DigiKey offer" — a real absence, not a zero to impute.

`components` and `distributor_offers` are created by SQLAlchemy `create_all`
(see app/main.py), not by an earlier migration — same situation as
`optimization_runs` in 0004/0005 — so on a fresh DB the models already emit these
columns and there is nothing to add. The guards below make this a no-op in that
case and only add columns on pre-existing DBs that predate this change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, type) — every one read straight off the DigiKey v4 product
# response by app/ml/lead_time_collector.py.
_NEW_COLUMNS = (
    # Part-level: properties of the component itself.
    ('components', 'lifecycle_status', sa.String(length=50)),          # ProductStatus.Status
    ('components', 'normally_stocked', sa.Boolean()),                  # NormallyStocking
    ('components', 'discontinued', sa.Boolean()),                      # Discontinued
    ('components', 'end_of_life', sa.Boolean()),                       # EndOfLife
    ('components', 'digikey_category', sa.String(length=200)),         # Category.Name
    ('components', 'digikey_subcategory', sa.String(length=200)),      # ChildCategories[0].Name
    # The ML TARGET, persisted so the optimizer can prefer a real quoted lead
    # time over a prediction. NOT a feature — using it as one is label leakage.
    ('components', 'observed_lead_time_weeks', sa.Float()),            # ManufacturerLeadWeeks
    ('components', 'lead_time_observed_at', sa.Date()),                # snapshot date
    # Offer-level: properties of a specific distributor's offer.
    ('distributor_offers', 'standard_pack', sa.Integer()),             # StandardPackage
    ('distributor_offers', 'packaging', sa.String(length=100)),        # PackageType.Name
)


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table, name, coltype in _NEW_COLUMNS:
        if not _has_column(bind, table, name):
            op.add_column(table, sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    for table in ('components', 'distributor_offers'):
        cols = [n for t, n, _ in _NEW_COLUMNS
                if t == table and _has_column(bind, table, n)]
        if not cols:
            continue
        with op.batch_alter_table(table) as batch_op:
            for name in cols:
                batch_op.drop_column(name)
