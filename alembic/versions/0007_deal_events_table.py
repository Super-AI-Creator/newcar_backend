"""deal events table

Revision ID: 0007_deal_events
Revises: 0006_lender_rates
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_deal_events"
down_revision = "0006_lender_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deal_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("deal_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deal_events_deal_id", "deal_events", ["deal_id"])
    op.create_index("ix_deal_events_actor_user_id", "deal_events", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_deal_events_actor_user_id", table_name="deal_events")
    op.drop_index("ix_deal_events_deal_id", table_name="deal_events")
    op.drop_table("deal_events")
