"""Optional invited member name and phone on personal invites.

Revision ID: 0031_member_invite_name_phone
Revises: 0030_users_email_auth_realm_unique
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_member_invite_name_phone"
down_revision = "0030_users_email_auth_realm_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credit_union_member_invites",
        sa.Column("invited_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "credit_union_member_invites",
        sa.Column("invited_phone", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credit_union_member_invites", "invited_phone")
    op.drop_column("credit_union_member_invites", "invited_name")
