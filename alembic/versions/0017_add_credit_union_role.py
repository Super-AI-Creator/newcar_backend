"""add credit_union to users.role enum (MySQL)

Revision ID: 0017_add_credit_union_role
Revises: 0016_credit_unions
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


revision = "0017_add_credit_union_role"
down_revision = "0016_credit_unions"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    if not _table_exists(inspector, table_name):
        return False
    return column_name in [c["name"] for c in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name.lower()

    if _table_exists(inspector, "users") and _column_exists(inspector, "users", "role") and dialect == "mysql":
        op.execute(
            "ALTER TABLE users "
            "MODIFY COLUMN role ENUM('customer','dealer','broker_admin','super_admin','credit_union') NOT NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name.lower()

    if _table_exists(inspector, "users") and _column_exists(inspector, "users", "role") and dialect == "mysql":
        op.execute("UPDATE users SET role='customer' WHERE role='credit_union'")
        op.execute(
            "ALTER TABLE users "
            "MODIFY COLUMN role ENUM('customer','dealer','broker_admin','super_admin') NOT NULL"
        )
