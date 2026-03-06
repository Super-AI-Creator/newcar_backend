"""lender rates table

Revision ID: 0006_lender_rates
Revises: 0005_deals
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_lender_rates"
down_revision = "0005_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lender_rates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("lender_name", sa.String(length=120), nullable=False),
        sa.Column("credit_tier", sa.String(length=20), nullable=False),
        sa.Column("vehicle_type", sa.String(length=20), nullable=False, server_default="all"),
        sa.Column("apr", sa.Numeric(6, 3), nullable=False),
        sa.Column("max_term_months", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lender_rates_lender_name", "lender_rates", ["lender_name"])
    op.create_index("ix_lender_rates_credit_tier", "lender_rates", ["credit_tier"])
    op.create_index("ix_lender_rates_vehicle_type", "lender_rates", ["vehicle_type"])


def downgrade() -> None:
    op.drop_index("ix_lender_rates_vehicle_type", table_name="lender_rates")
    op.drop_index("ix_lender_rates_credit_tier", table_name="lender_rates")
    op.drop_index("ix_lender_rates_lender_name", table_name="lender_rates")
    op.drop_table("lender_rates")
