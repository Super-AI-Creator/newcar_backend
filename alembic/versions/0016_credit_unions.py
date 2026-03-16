"""credit unions, loan programs, disclosures, member approvals

Revision ID: 0016_credit_unions
Revises: 0015_super_admin_seo
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa


revision = "0016_credit_unions"
down_revision = "0015_super_admin_seo"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "credit_unions"):
        op.create_table(
            "credit_unions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("logo_url", sa.String(500), nullable=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("contact_name", sa.String(255), nullable=True),
            sa.Column("contact_phone", sa.String(50), nullable=True),
            sa.Column("contact_email", sa.String(255), nullable=True),
            sa.Column("signup_token", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_credit_unions_slug"),
            sa.UniqueConstraint("signup_token", name="uq_credit_unions_signup_token"),
        )
        op.create_index("ix_credit_unions_slug", "credit_unions", ["slug"])
        op.create_index("ix_credit_unions_signup_token", "credit_unions", ["signup_token"])

    if not _table_exists(inspector, "credit_union_loan_programs"):
        op.create_table(
            "credit_union_loan_programs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("credit_union_id", sa.BigInteger(), nullable=False),
            sa.Column("interest_rate", sa.Numeric(6, 3), nullable=False),
            sa.Column("max_term_months", sa.Integer(), nullable=False),
            sa.Column("vehicle_type", sa.String(20), nullable=False, server_default="new"),
            sa.ForeignKeyConstraint(["credit_union_id"], ["credit_unions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_credit_union_loan_programs_credit_union_id", "credit_union_loan_programs", ["credit_union_id"])

    if not _table_exists(inspector, "credit_union_disclosures"):
        op.create_table(
            "credit_union_disclosures",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("credit_union_id", sa.BigInteger(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("text", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["credit_union_id"], ["credit_unions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_credit_union_disclosures_credit_union_id", "credit_union_disclosures", ["credit_union_id"])

    if _table_exists(inspector, "users"):
        cols = [c["name"] for c in inspector.get_columns("users")]
        if "credit_union_id" not in cols:
            op.add_column("users", sa.Column("credit_union_id", sa.BigInteger(), nullable=True))
            op.create_foreign_key("fk_users_credit_union_id", "users", "credit_unions", ["credit_union_id"], ["id"], ondelete="SET NULL")
            op.create_index("ix_users_credit_union_id", "users", ["credit_union_id"])

    if not _table_exists(inspector, "cu_member_approvals"):
        op.create_table(
            "cu_member_approvals",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("credit_union_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column("loan_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("term_months", sa.Integer(), nullable=False),
            sa.Column("special_notes", sa.Text(), nullable=True),
            sa.Column("approval_code", sa.String(64), nullable=False),
            sa.Column("member_phone", sa.String(50), nullable=True),
            sa.Column("member_email", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["credit_union_id"], ["credit_unions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("approval_code", name="uq_cu_member_approvals_approval_code"),
        )
        op.create_index("ix_cu_member_approvals_credit_union_id", "cu_member_approvals", ["credit_union_id"])
        op.create_index("ix_cu_member_approvals_user_id", "cu_member_approvals", ["user_id"])
        op.create_index("ix_cu_member_approvals_approval_code", "cu_member_approvals", ["approval_code"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "cu_member_approvals"):
        op.drop_index("ix_cu_member_approvals_approval_code", table_name="cu_member_approvals")
        op.drop_index("ix_cu_member_approvals_user_id", table_name="cu_member_approvals")
        op.drop_index("ix_cu_member_approvals_credit_union_id", table_name="cu_member_approvals")
        op.drop_table("cu_member_approvals")

    if _table_exists(inspector, "users"):
        cols = [c["name"] for c in inspector.get_columns("users")]
        if "credit_union_id" in cols:
            op.drop_constraint("fk_users_credit_union_id", "users", type_="foreignkey")
            op.drop_index("ix_users_credit_union_id", table_name="users")
            op.drop_column("users", "credit_union_id")

    if _table_exists(inspector, "credit_union_disclosures"):
        op.drop_index("ix_credit_union_disclosures_credit_union_id", table_name="credit_union_disclosures")
        op.drop_table("credit_union_disclosures")

    if _table_exists(inspector, "credit_union_loan_programs"):
        op.drop_index("ix_credit_union_loan_programs_credit_union_id", table_name="credit_union_loan_programs")
        op.drop_table("credit_union_loan_programs")

    if _table_exists(inspector, "credit_unions"):
        op.drop_index("ix_credit_unions_signup_token", table_name="credit_unions")
        op.drop_index("ix_credit_unions_slug", table_name="credit_unions")
        op.drop_table("credit_unions")
