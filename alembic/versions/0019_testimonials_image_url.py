"""add image_url to testimonials

Revision ID: 0019_testimonials_image_url
Revises: 0018_landing_page_content
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa

revision = "0019_testimonials_image_url"
down_revision = "0018_landing_page_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("testimonials", sa.Column("image_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("testimonials", "image_url")

