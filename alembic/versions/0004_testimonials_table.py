"""testimonials table

Revision ID: 0004_testimonials
Revises: 0003_add_year_to_model_scores
Create Date: 2026-02-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0004_testimonials"
down_revision = "0003_add_year_to_model_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "testimonials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("testimonials")
