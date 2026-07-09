"""store_schema_versions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_schema_versions",
        sa.Column("store_name", sa.String(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("store_schema_versions")
