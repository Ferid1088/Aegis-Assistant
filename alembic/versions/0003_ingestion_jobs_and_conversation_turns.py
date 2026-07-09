"""ingestion_jobs + conversation_turns

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("uploaded_by", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("staged_path", sa.String(), nullable=False),
        sa.Column("doc_version", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("logical_doc_id", sa.String(), nullable=True),
        sa.Column("indexed_count", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ingestion_jobs_uploaded_by", "ingestion_jobs", ["uploaded_by"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("standalone_question", sa.String(), nullable=False),
        sa.Column("answer", sa.String(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("conversation_id", "turn_index", name="uq_conversation_turn_index"),
    )
    op.create_index("ix_conversation_turns_conversation_id", "conversation_turns", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("conversation_turns")
    op.drop_table("ingestion_jobs")
