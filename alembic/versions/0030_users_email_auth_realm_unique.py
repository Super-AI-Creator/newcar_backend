"""Allow same email on carscu vs newcar_superstore (composite unique).

Revision ID: 0030_users_email_auth_realm_unique
Revises: 0029_users_auth_realm
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_users_email_auth_realm_unique"
down_revision = "0029_users_auth_realm"
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

    # Backfill NULL/empty auth_realm before NOT NULL + composite unique.
    op.execute(
        sa.text(
            "UPDATE users SET auth_realm = 'carscu' "
            "WHERE (auth_realm IS NULL OR TRIM(auth_realm) = '') AND credit_union_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE users SET auth_realm = 'carscu' "
            "WHERE (auth_realm IS NULL OR TRIM(auth_realm) = '') AND role = 'credit_union'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE users SET auth_realm = 'newcar_superstore' "
            "WHERE auth_realm IS NULL OR TRIM(auth_realm) = ''"
        )
    )

    op.alter_column(
        "users",
        "auth_realm",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    inspector = sa.inspect(bind)
    for uc in inspector.get_unique_constraints("users"):
        cols_uc = list(uc.get("column_names") or [])
        if cols_uc == ["email"]:
            op.drop_constraint(uc["name"], "users", type_="unique")
            break
    else:
        try:
            op.drop_constraint("uq_users_email", "users", type_="unique")
        except Exception:
            pass

    op.create_unique_constraint("uq_users_email_auth_realm", "users", ["email", "auth_realm"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    try:
        op.drop_constraint("uq_users_email_auth_realm", "users", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_users_email", "users", ["email"])
