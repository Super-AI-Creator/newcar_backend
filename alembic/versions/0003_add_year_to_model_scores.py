"""add year to model scores

Revision ID: 0003_add_year_to_model_scores
Revises: 0002_add_password_hash_to_users
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_year_to_model_scores"
down_revision = "0002_add_password_hash_to_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_scores", sa.Column("year", sa.Integer(), nullable=True))
    op.create_index("ix_model_scores_year", "model_scores", ["year"])

    op.drop_constraint("uq_model_scores_make_model_trim", "model_scores", type_="unique")
    op.create_unique_constraint(
        "uq_model_scores_make_model_trim_year",
        "model_scores",
        ["make", "model", "trim", "year"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_model_scores_make_model_trim_year", "model_scores", type_="unique")
    op.create_unique_constraint(
        "uq_model_scores_make_model_trim",
        "model_scores",
        ["make", "model", "trim"],
    )

    op.drop_index("ix_model_scores_year", table_name="model_scores")
    op.drop_column("model_scores", "year")
