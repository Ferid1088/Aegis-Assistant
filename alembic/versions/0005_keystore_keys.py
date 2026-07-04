"""keystore_keys

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "keystore_keys",
        sa.Column("purpose", sa.String(), primary_key=True),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("keystore_keys")
