"""articles table for admin-managed content

Revision ID: 0021_articles
Revises: 0020_cu_white_label
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa

revision = "0021_articles"
down_revision = "0020_cu_white_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("date", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_articles_slug"),
    )
    op.create_index("ix_articles_slug", "articles", ["slug"])


def downgrade() -> None:
    op.drop_index("ix_articles_slug", table_name="articles")
    op.drop_table("articles")
