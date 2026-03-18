"""add cached homepage featured card payload

Revision ID: 0022_homepage_featured_card_payload
Revises: 0021_articles
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_homepage_featured_card_payload"
down_revision = "0021_articles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "homepage_featured_vehicles",
        sa.Column("card_payload_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("homepage_featured_vehicles", "card_payload_json")

