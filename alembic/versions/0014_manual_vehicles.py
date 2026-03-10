"""add manual vehicles table

Revision ID: 0014_manual_vehicles
Revises: 0013_super_admin_homepg
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_manual_vehicles"
down_revision = "0013_super_admin_homepg"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "manual_vehicles"):
        op.create_table(
            "manual_vehicles",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
            sa.Column("vin", sa.String(length=32), nullable=False),
            sa.Column("vehicle_type", sa.String(length=10), server_default="new", nullable=False),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("make", sa.String(length=100), nullable=True),
            sa.Column("model", sa.String(length=120), nullable=True),
            sa.Column("trim", sa.String(length=120), nullable=True),
            sa.Column("msrp", sa.Float(), nullable=True),
            sa.Column("listed_price", sa.Float(), nullable=True),
            sa.Column("mileage", sa.Integer(), nullable=True),
            sa.Column("condition", sa.String(length=20), nullable=True),
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("photos_json", sa.Text(), nullable=True),
            sa.Column("dealer_name", sa.String(length=160), nullable=True),
            sa.Column("dealer_phone", sa.String(length=40), nullable=True),
            sa.Column("listing_url", sa.String(length=500), nullable=True),
            sa.Column("carfax_url", sa.String(length=500), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
            sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("vin", name="uq_manual_vehicles_vin"),
        )

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "manual_vehicles") and not _index_exists(inspector, "manual_vehicles", "ix_manual_vehicles_vin"):
        op.create_index("ix_manual_vehicles_vin", "manual_vehicles", ["vin"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "manual_vehicles"):
        if _index_exists(inspector, "manual_vehicles", "ix_manual_vehicles_vin"):
            op.drop_index("ix_manual_vehicles_vin", table_name="manual_vehicles")
        op.drop_table("manual_vehicles")
