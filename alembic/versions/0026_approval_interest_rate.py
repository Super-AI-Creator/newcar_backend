from alembic import op
import sqlalchemy as sa


revision = "0026_approval_interest_rate"
down_revision = "0025_credit_union_member_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cu_member_approvals" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("cu_member_approvals")]
    if "interest_rate" not in cols:
        op.add_column("cu_member_approvals", sa.Column("interest_rate", sa.Numeric(6, 3), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cu_member_approvals" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("cu_member_approvals")]
    if "interest_rate" in cols:
        op.drop_column("cu_member_approvals", "interest_rate")
