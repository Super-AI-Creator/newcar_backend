"""credit and docs management tables

Revision ID: 0009_credit_docs_management
Revises: 0008_deals_assignment_delivery
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_credit_docs_management"
down_revision = "0008_deals_assignment_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("credit_applications", "user_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("credit_applications", sa.Column("source", sa.String(length=30), nullable=False, server_default="authenticated"))
    op.add_column("credit_applications", sa.Column("status", sa.String(length=30), nullable=False, server_default="submitted"))
    op.add_column("credit_applications", sa.Column("broker_note", sa.Text(), nullable=True))
    op.add_column("credit_applications", sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True))
    op.add_column("credit_applications", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column(
        "credit_applications",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_credit_applications_source", "credit_applications", ["source"])
    op.create_index("ix_credit_applications_status", "credit_applications", ["status"])
    op.create_index("ix_credit_applications_reviewed_by_user_id", "credit_applications", ["reviewed_by_user_id"])
    op.create_foreign_key(
        "fk_credit_applications_reviewed_by_user_id_users",
        "credit_applications",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
    )

    op.create_table(
        "document_submissions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="submitted"),
        sa.Column("broker_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("drivers_license_filename", sa.String(length=255), nullable=True),
        sa.Column("drivers_license_content_type", sa.String(length=120), nullable=True),
        sa.Column("drivers_license_bytes", sa.LargeBinary(length=(2**24) - 1), nullable=True),
        sa.Column("insurance_filename", sa.String(length=255), nullable=True),
        sa.Column("insurance_content_type", sa.String(length=120), nullable=True),
        sa.Column("insurance_bytes", sa.LargeBinary(length=(2**24) - 1), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_document_submissions_user_id", "document_submissions", ["user_id"])
    op.create_index("ix_document_submissions_vin", "document_submissions", ["vin"])
    op.create_index("ix_document_submissions_status", "document_submissions", ["status"])
    op.create_index("ix_document_submissions_reviewed_by_user_id", "document_submissions", ["reviewed_by_user_id"])
    op.create_index("ix_document_submissions_created_at", "document_submissions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_document_submissions_created_at", table_name="document_submissions")
    op.drop_index("ix_document_submissions_reviewed_by_user_id", table_name="document_submissions")
    op.drop_index("ix_document_submissions_status", table_name="document_submissions")
    op.drop_index("ix_document_submissions_vin", table_name="document_submissions")
    op.drop_index("ix_document_submissions_user_id", table_name="document_submissions")
    op.drop_table("document_submissions")

    op.drop_constraint("fk_credit_applications_reviewed_by_user_id_users", "credit_applications", type_="foreignkey")
    op.drop_index("ix_credit_applications_reviewed_by_user_id", table_name="credit_applications")
    op.drop_index("ix_credit_applications_status", table_name="credit_applications")
    op.drop_index("ix_credit_applications_source", table_name="credit_applications")
    op.drop_column("credit_applications", "updated_at")
    op.drop_column("credit_applications", "reviewed_at")
    op.drop_column("credit_applications", "reviewed_by_user_id")
    op.drop_column("credit_applications", "broker_note")
    op.drop_column("credit_applications", "status")
    op.drop_column("credit_applications", "source")
    op.alter_column("credit_applications", "user_id", existing_type=sa.BigInteger(), nullable=False)
