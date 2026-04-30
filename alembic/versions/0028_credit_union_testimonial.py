from alembic import op
import sqlalchemy as sa


revision = "0028_credit_union_testimonial"
down_revision = "0027_cu_approval_member_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "credit_unions" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("credit_unions")]
    if "testimonial_image_url" not in cols:
        op.add_column("credit_unions", sa.Column("testimonial_image_url", sa.String(length=500), nullable=True))
    if "testimonial_text" not in cols:
        op.add_column("credit_unions", sa.Column("testimonial_text", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "credit_unions" not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns("credit_unions")]
    if "testimonial_text" in cols:
        op.drop_column("credit_unions", "testimonial_text")
    if "testimonial_image_url" in cols:
        op.drop_column("credit_unions", "testimonial_image_url")
