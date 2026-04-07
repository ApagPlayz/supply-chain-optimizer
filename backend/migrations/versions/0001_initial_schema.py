"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('factory_name', sa.String(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # production_hubs
    op.create_table(
        'production_hubs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('city', sa.String(100), nullable=False),
        sa.Column('state', sa.String(2), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('hub_type', sa.String(100)),
        sa.Column('specialization', sa.Text()),
        sa.Column('description', sa.Text()),
        sa.Column('active_suppliers', sa.Integer(), server_default='0'),
        sa.Column('risk_index', sa.Float(), server_default='0.0'),
    )

    # materials
    op.create_table(
        'materials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('subcategory', sa.String(100)),
        sa.Column('unit', sa.String(50), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('cas_number', sa.String(20)),
        sa.Column('current_price', sa.Float()),
        sa.Column('price_unit', sa.String(50)),
        sa.Column('volatility_score', sa.Float(), server_default='0.5'),
        sa.Column('supply_risk_score', sa.Float(), server_default='0.5'),
        sa.Column('fred_series_id', sa.String(50)),
        sa.Column('alpha_vantage_symbol', sa.String(20)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_materials_name', 'materials', ['name'])
    op.create_index('ix_materials_category', 'materials', ['category'])

    # price_history
    op.create_table(
        'price_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('material_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('source', sa.String(50)),
    )
    op.create_index('ix_price_history_material_id', 'price_history', ['material_id'])
    op.create_index('ix_price_history_date', 'price_history', ['date'])

    # price_forecasts
    op.create_table(
        'price_forecasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('material_id', sa.Integer(), nullable=False),
        sa.Column('forecast_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('predicted_price', sa.Float(), nullable=False),
        sa.Column('lower_ci', sa.Float()),
        sa.Column('upper_ci', sa.Float()),
        sa.Column('model_version', sa.String(50)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_price_forecasts_material_id', 'price_forecasts', ['material_id'])

    # suppliers
    op.create_table(
        'suppliers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('hub_id', sa.Integer(), sa.ForeignKey('production_hubs.id'), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('city', sa.String(100)),
        sa.Column('state', sa.String(2)),
        sa.Column('materials_supplied', sa.Text()),
        sa.Column('lead_time_days', sa.Integer(), server_default='7'),
        sa.Column('reliability_score', sa.Float(), server_default='0.8'),
        sa.Column('risk_score', sa.Float(), server_default='0.3'),
        sa.Column('financial_health', sa.Float(), server_default='0.7'),
        sa.Column('geo_risk', sa.Float(), server_default='0.2'),
        sa.Column('weather_risk', sa.Float(), server_default='0.2'),
        sa.Column('price_competitiveness', sa.Float(), server_default='0.7'),
        sa.Column('annual_capacity_kg', sa.Float()),
        sa.Column('certifications', sa.Text()),
        sa.Column('is_domestic', sa.Boolean(), server_default='true'),
        sa.Column('description', sa.Text()),
    )
    op.create_index('ix_suppliers_hub_id', 'suppliers', ['hub_id'])

    # cart_items
    op.create_table(
        'cart_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id'), nullable=False),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(50)),
        sa.Column('unit_price', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_cart_items_user_id', 'cart_items', ['user_id'])

    # orders
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(50), server_default='pending'),
        sa.Column('total_cost', sa.Float()),
        sa.Column('total_co2e_kg', sa.Float()),
        sa.Column('eta_days', sa.Float()),
        sa.Column('eta_lower_ci', sa.Float()),
        sa.Column('eta_upper_ci', sa.Float()),
        sa.Column('optimized_route', sa.JSON()),
        sa.Column('monte_carlo_results', sa.JSON()),
        sa.Column('items', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_orders_user_id', 'orders', ['user_id'])


def downgrade() -> None:
    op.drop_table('orders')
    op.drop_table('cart_items')
    op.drop_table('suppliers')
    op.drop_table('price_forecasts')
    op.drop_table('price_history')
    op.drop_table('materials')
    op.drop_table('production_hubs')
    op.drop_table('users')
