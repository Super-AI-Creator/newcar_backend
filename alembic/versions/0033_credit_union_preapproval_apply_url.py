"""Per-CU URL for Step 1 Apply now on public partner landing.

Revision ID: 0033_credit_union_preapproval_apply_url
Revises: 0032_credit_union_primary_staff
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_credit_union_preapproval_apply_url"
down_revision = "0032_credit_union_primary_staff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credit_unions",
        sa.Column("preapproval_apply_url", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credit_unions", "preapproval_apply_url")
