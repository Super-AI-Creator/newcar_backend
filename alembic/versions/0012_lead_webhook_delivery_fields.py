"""add webhook delivery tracking fields to lead_requests

Revision ID: 0012_lead_webhook_fields
Revises: 0011_lead_requests_table
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_lead_webhook_fields"
down_revision = "0011_lead_requests_table"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _column_exists(inspector, "lead_requests", "webhook_status"):
        op.add_column(
            "lead_requests",
            sa.Column("webhook_status", sa.String(length=30), server_default="pending", nullable=False),
        )
    if not _column_exists(inspector, "lead_requests", "webhook_attempts"):
        op.add_column(
            "lead_requests",
            sa.Column("webhook_attempts", sa.Integer(), server_default="0", nullable=False),
        )
    if not _column_exists(inspector, "lead_requests", "webhook_last_error"):
        op.add_column("lead_requests", sa.Column("webhook_last_error", sa.Text(), nullable=True))
    if not _column_exists(inspector, "lead_requests", "webhook_last_attempt_at"):
        op.add_column("lead_requests", sa.Column("webhook_last_attempt_at", sa.DateTime(), nullable=True))
    if not _column_exists(inspector, "lead_requests", "webhook_delivered_at"):
        op.add_column("lead_requests", sa.Column("webhook_delivered_at", sa.DateTime(), nullable=True))

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "lead_requests", "ix_lead_requests_webhook_status"):
        op.create_index("ix_lead_requests_webhook_status", "lead_requests", ["webhook_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _index_exists(inspector, "lead_requests", "ix_lead_requests_webhook_status"):
        op.drop_index("ix_lead_requests_webhook_status", table_name="lead_requests")

    inspector = sa.inspect(bind)
    if _column_exists(inspector, "lead_requests", "webhook_delivered_at"):
        op.drop_column("lead_requests", "webhook_delivered_at")
    if _column_exists(inspector, "lead_requests", "webhook_last_attempt_at"):
        op.drop_column("lead_requests", "webhook_last_attempt_at")
    if _column_exists(inspector, "lead_requests", "webhook_last_error"):
        op.drop_column("lead_requests", "webhook_last_error")
    if _column_exists(inspector, "lead_requests", "webhook_attempts"):
        op.drop_column("lead_requests", "webhook_attempts")
    if _column_exists(inspector, "lead_requests", "webhook_status"):
        op.drop_column("lead_requests", "webhook_status")
