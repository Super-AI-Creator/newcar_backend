"""add super_admin role and homepage featured vehicles

Revision ID: 0013_super_admin_homepg
Revises: 0012_lead_webhook_fields
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_super_admin_homepg"
down_revision = "0012_lead_webhook_fields"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name.lower()

    if _table_exists(inspector, "users") and _column_exists(inspector, "users", "role") and dialect == "mysql":
        op.execute(
            "ALTER TABLE users "
            "MODIFY COLUMN role ENUM('customer','dealer','broker_admin','super_admin') NOT NULL"
        )

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "homepage_featured_vehicles"):
        op.create_table(
            "homepage_featured_vehicles",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
            sa.Column("month_key", sa.String(length=7), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("vin", sa.String(length=32), nullable=False),
            sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], name="fk_homepage_featured_updated_by"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("month_key", "position", name="uq_homepage_featured_month_position"),
            sa.UniqueConstraint("month_key", "vin", name="uq_homepage_featured_month_vin"),
        )

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "homepage_featured_vehicles") and not _index_exists(
        inspector, "homepage_featured_vehicles", "ix_homepage_featured_vehicles_month_key"
    ):
        op.create_index(
            "ix_homepage_featured_vehicles_month_key",
            "homepage_featured_vehicles",
            ["month_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name.lower()

    if _table_exists(inspector, "homepage_featured_vehicles"):
        if _index_exists(inspector, "homepage_featured_vehicles", "ix_homepage_featured_vehicles_month_key"):
            op.drop_index("ix_homepage_featured_vehicles_month_key", table_name="homepage_featured_vehicles")
        op.drop_table("homepage_featured_vehicles")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "users") and _column_exists(inspector, "users", "role") and dialect == "mysql":
        op.execute("UPDATE users SET role='broker_admin' WHERE role='super_admin'")
        op.execute(
            "ALTER TABLE users "
            "MODIFY COLUMN role ENUM('customer','dealer','broker_admin') NOT NULL"
        )
