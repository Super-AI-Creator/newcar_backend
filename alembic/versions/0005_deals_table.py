"""deals table

Revision ID: 0005_deals
Revises: 0004_testimonials
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_deals"
down_revision = "0004_testimonials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("vin", sa.String(length=17), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "inquiry",
                "broker_review",
                "offer_ready",
                "locked",
                "docs_pending",
                "delivered",
                "cancelled",
                name="deal_status",
            ),
            nullable=False,
        ),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column("broker_note", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deals_user_id", "deals", ["user_id"])
    op.create_index("ix_deals_vin", "deals", ["vin"])
    op.create_index("ix_deals_status", "deals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_deals_status", table_name="deals")
    op.drop_index("ix_deals_vin", table_name="deals")
    op.drop_index("ix_deals_user_id", table_name="deals")
    op.drop_table("deals")
