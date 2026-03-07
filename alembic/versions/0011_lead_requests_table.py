"""create lead_requests table

Revision ID: 0011_lead_requests_table
Revises: 0010_offer_override_term_miles
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_lead_requests_table"
down_revision = "0010_offer_override_term_miles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("make", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("trim", sa.String(length=160), nullable=True),
        sa.Column("vehicle", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=60), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_requests_user_id", "lead_requests", ["user_id"])
    op.create_index("ix_lead_requests_vin", "lead_requests", ["vin"])
    op.create_index("ix_lead_requests_email", "lead_requests", ["email"])
    op.create_index("ix_lead_requests_source", "lead_requests", ["source"])
    op.create_index("ix_lead_requests_created_at", "lead_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_requests_created_at", table_name="lead_requests")
    op.drop_index("ix_lead_requests_source", table_name="lead_requests")
    op.drop_index("ix_lead_requests_email", table_name="lead_requests")
    op.drop_index("ix_lead_requests_vin", table_name="lead_requests")
    op.drop_index("ix_lead_requests_user_id", table_name="lead_requests")
    op.drop_table("lead_requests")
