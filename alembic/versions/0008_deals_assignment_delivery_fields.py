"""deals assignment and delivery fields

Revision ID: 0008_deals_assignment_delivery
Revises: 0007_deal_events
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_deals_assignment_delivery"
down_revision = "0007_deal_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("assigned_broker_user_id", sa.BigInteger(), nullable=True))
    op.add_column("deals", sa.Column("delivery_scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("deals", sa.Column("delivery_address", sa.String(length=255), nullable=True))
    op.add_column("deals", sa.Column("delivery_city", sa.String(length=120), nullable=True))
    op.add_column("deals", sa.Column("delivery_state", sa.String(length=120), nullable=True))
    op.add_column("deals", sa.Column("delivery_zip", sa.String(length=30), nullable=True))
    op.add_column("deals", sa.Column("delivery_notes", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_deals_assigned_broker_user_id_users",
        "deals",
        "users",
        ["assigned_broker_user_id"],
        ["id"],
    )
    op.create_index("ix_deals_assigned_broker_user_id", "deals", ["assigned_broker_user_id"])


def downgrade() -> None:
    op.drop_index("ix_deals_assigned_broker_user_id", table_name="deals")
    op.drop_constraint("fk_deals_assigned_broker_user_id_users", "deals", type_="foreignkey")
    op.drop_column("deals", "delivery_notes")
    op.drop_column("deals", "delivery_zip")
    op.drop_column("deals", "delivery_state")
    op.drop_column("deals", "delivery_city")
    op.drop_column("deals", "delivery_address")
    op.drop_column("deals", "delivery_scheduled_at")
    op.drop_column("deals", "assigned_broker_user_id")
