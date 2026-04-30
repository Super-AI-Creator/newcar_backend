from alembic import op
import sqlalchemy as sa


revision = "0029_users_auth_realm"
down_revision = "0028_credit_union_testimonial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "auth_realm" not in cols:
        op.add_column("users", sa.Column("auth_realm", sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "auth_realm" in cols:
        op.drop_column("users", "auth_realm")
