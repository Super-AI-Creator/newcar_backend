"""credit union white-label: banner_url, hero_title, hero_subtitle

Revision ID: 0020_cu_white_label
Revises: 0019_testimonials_image_url
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa

revision = "0020_cu_white_label"
down_revision = "0019_testimonials_image_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credit_unions", sa.Column("banner_url", sa.String(500), nullable=True))
    op.add_column("credit_unions", sa.Column("hero_title", sa.String(255), nullable=True))
    op.add_column("credit_unions", sa.Column("hero_subtitle", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_unions", "hero_subtitle")
    op.drop_column("credit_unions", "hero_title")
    op.drop_column("credit_unions", "banner_url")
