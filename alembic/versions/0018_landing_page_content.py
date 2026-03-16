"""landing page content for admin-editable hero, lease, how it works

Revision ID: 0018_landing_page_content
Revises: 0017_add_credit_union_role
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


revision = "0018_landing_page_content"
down_revision = "0017_add_credit_union_role"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "landing_page_content"):
        op.create_table(
            "landing_page_content",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute("INSERT INTO landing_page_content (id, content) VALUES (1, '{}')")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "landing_page_content"):
        op.drop_table("landing_page_content")
