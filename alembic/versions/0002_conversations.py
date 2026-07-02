"""conversations + conversation_grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("erasure_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("encryption_key_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "conversation_grants",
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission", sa.String(), nullable=False, server_default="read"),
        sa.CheckConstraint("permission IN ('read','write','admin')", name="ck_conversation_grant_permission"),
    )


def downgrade() -> None:
    op.drop_table("conversation_grants")
    op.drop_table("conversations")
