from alembic import op
import sqlalchemy as sa


revision = "0027_cu_approval_member_name"
down_revision = "0026_approval_interest_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cu_member_approvals" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("cu_member_approvals")]
    if "member_name" not in cols:
        op.add_column("cu_member_approvals", sa.Column("member_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cu_member_approvals" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("cu_member_approvals")]
    if "member_name" in cols:
        op.drop_column("cu_member_approvals", "member_name")
