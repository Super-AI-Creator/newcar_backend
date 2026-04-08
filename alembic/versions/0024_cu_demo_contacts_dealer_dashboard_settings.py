from alembic import op
import sqlalchemy as sa


revision = "0024_cu_demo_contacts_dealer_dashboard"
down_revision = "0023_cu_fields_on_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cu_demo_contacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("cu_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cu_demo_contacts_email", "cu_demo_contacts", ["email"], unique=False)

    op.create_table(
        "dealer_dashboard_settings",
        sa.Column("dealer_source_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("dashboard_activated", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("dealer_source_id"),
    )


def downgrade() -> None:
    op.drop_table("dealer_dashboard_settings")
    op.drop_index("ix_cu_demo_contacts_email", table_name="cu_demo_contacts")
    op.drop_table("cu_demo_contacts")
