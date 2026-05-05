"""Primary CU staff user for admin main-login and impersonation.

Revision ID: 0032_credit_union_primary_staff
Revises: 0031_member_invite_name_phone
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_credit_union_primary_staff"
down_revision = "0031_member_invite_name_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credit_unions",
        sa.Column("primary_staff_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_credit_unions_primary_staff_user_id_users",
        "credit_unions",
        "users",
        ["primary_staff_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_credit_unions_primary_staff_user_id_users", "credit_unions", type_="foreignkey")
    op.drop_column("credit_unions", "primary_staff_user_id")
