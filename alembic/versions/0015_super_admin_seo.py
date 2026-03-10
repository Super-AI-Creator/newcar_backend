"""add super admin seo page settings

Revision ID: 0015_super_admin_seo
Revises: 0014_manual_vehicles
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_super_admin_seo"
down_revision = "0014_manual_vehicles"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "seo_page_settings"):
        op.create_table(
            "seo_page_settings",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
            sa.Column("page_key", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("keywords", sa.String(length=1000), nullable=True),
            sa.Column("canonical_url", sa.String(length=500), nullable=True),
            sa.Column("og_title", sa.String(length=255), nullable=True),
            sa.Column("og_description", sa.String(length=500), nullable=True),
            sa.Column("og_image_url", sa.String(length=500), nullable=True),
            sa.Column("robots", sa.String(length=120), nullable=True),
            sa.Column("json_ld_text", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
            sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("page_key", name="uq_seo_page_settings_page_key"),
        )

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "seo_page_settings") and not _index_exists(inspector, "seo_page_settings", "ix_seo_page_settings_page_key"):
        op.create_index("ix_seo_page_settings_page_key", "seo_page_settings", ["page_key"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "seo_page_settings"):
        if _index_exists(inspector, "seo_page_settings", "ix_seo_page_settings_page_key"):
            op.drop_index("ix_seo_page_settings_page_key", table_name="seo_page_settings")
        op.drop_table("seo_page_settings")
