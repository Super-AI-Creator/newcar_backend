from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0023_cu_fields_on_deals"
down_revision = "0022_homepage_featured_card_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("credit_union_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("cu_approval_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_deals_credit_union",
        "deals",
        "credit_unions",
        ["credit_union_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_deals_cu_approval",
        "deals",
        "cu_member_approvals",
        ["cu_approval_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_deals_cu_approval", "deals", type_="foreignkey")
    op.drop_constraint("fk_deals_credit_union", "deals", type_="foreignkey")
    op.drop_column("deals", "cu_approval_id")
    op.drop_column("deals", "credit_union_id")

