from alembic import op
import sqlalchemy as sa


revision = "0025_credit_union_member_invites"
down_revision = "0024_cu_demo_contacts_dealer_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_union_member_invites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("credit_union_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("invited_email", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("used_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["credit_union_id"], ["credit_unions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_credit_union_member_invites_token"),
    )
    op.create_index(
        "ix_credit_union_member_invites_credit_union_id",
        "credit_union_member_invites",
        ["credit_union_id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_union_member_invites_token",
        "credit_union_member_invites",
        ["token"],
        unique=False,
    )
    op.create_index(
        "ix_credit_union_member_invites_used_at",
        "credit_union_member_invites",
        ["used_at"],
        unique=False,
    )
    op.create_index(
        "ix_credit_union_member_invites_created_by_user_id",
        "credit_union_member_invites",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_credit_union_member_invites_created_by_user_id", table_name="credit_union_member_invites")
    op.drop_index("ix_credit_union_member_invites_used_at", table_name="credit_union_member_invites")
    op.drop_index("ix_credit_union_member_invites_token", table_name="credit_union_member_invites")
    op.drop_index("ix_credit_union_member_invites_credit_union_id", table_name="credit_union_member_invites")
    op.drop_table("credit_union_member_invites")
