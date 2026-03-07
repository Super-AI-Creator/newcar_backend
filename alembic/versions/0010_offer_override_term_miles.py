"""add term and miles fields to offer_overrides

Revision ID: 0010_offer_override_term_miles
Revises: 0009_credit_docs_management
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_offer_override_term_miles"
down_revision = "0009_credit_docs_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("offer_overrides", sa.Column("term_months", sa.BigInteger(), nullable=True))
    op.add_column("offer_overrides", sa.Column("miles_per_year", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("offer_overrides", "miles_per_year")
    op.drop_column("offer_overrides", "term_months")
