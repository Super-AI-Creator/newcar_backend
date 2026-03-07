"""create app backend tables

Revision ID: 0001_app_tables
Revises: 
Create Date: 2026-02-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_app_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("customer", "dealer", "broker_admin", name="user_role"), nullable=False),
        sa.Column("is_phone_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "auth_otps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.Enum("email", "sms", name="otp_channel"), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_auth_otps_user_id", "auth_otps", ["user_id"])

    op.create_table(
        "offer_overrides",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("vin", sa.String(length=17), nullable=False),
        sa.Column("down_payment", sa.Numeric(12, 2), nullable=True),
        sa.Column("monthly_payment", sa.Numeric(12, 2), nullable=True),
        sa.Column("discounted_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("visible_down_payment", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("visible_monthly", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("visible_discounted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.Enum("sheet", "dealer", "broker", name="offer_source"), nullable=False),
        sa.Column("updated_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("vin", name="uq_offer_overrides_vin"),
    )
    op.create_index("ix_offer_overrides_vin", "offer_overrides", ["vin"])
    op.create_index("ix_offer_overrides_source", "offer_overrides", ["source"])

    op.create_table(
        "model_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("make", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("trim", sa.String(length=100), nullable=True),
        sa.Column("design", sa.Integer(), nullable=False),
        sa.Column("performance", sa.Integer(), nullable=False),
        sa.Column("technology", sa.Integer(), nullable=False),
        sa.Column("practicality", sa.Integer(), nullable=False),
        sa.Column("future_value", sa.Integer(), nullable=False),
        sa.UniqueConstraint("make", "model", "trim", name="uq_model_scores_make_model_trim"),
    )
    op.create_index("ix_model_scores_make", "model_scores", ["make"])
    op.create_index("ix_model_scores_model", "model_scores", ["model"])
    op.create_index("ix_model_scores_trim", "model_scores", ["trim"])

    op.create_table(
        "favorites",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vin", sa.String(length=17), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("user_id", "vin", name="uq_favorites_user_vin"),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])
    op.create_index("ix_favorites_vin", "favorites", ["vin"])

    op.create_table(
        "broker_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("message_text", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("broker_admin_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_broker_messages_user_id", "broker_messages", ["user_id"])
    op.create_index("ix_broker_messages_vin", "broker_messages", ["vin"])

    op.create_table(
        "credit_applications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_credit_applications_user_id", "credit_applications", ["user_id"])
    op.create_index("ix_credit_applications_vin", "credit_applications", ["vin"])

    op.create_table(
        "sheet_sources_meta",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("sheet_id", sa.String(length=255), nullable=False),
        sa.Column("tab_name", sa.String(length=255), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_row_hash", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sheet_sources_meta")
    op.drop_table("credit_applications")
    op.drop_table("broker_messages")
    op.drop_table("favorites")
    op.drop_table("model_scores")
    op.drop_table("offer_overrides")
    op.drop_table("auth_otps")
    op.drop_table("users")
