"""document_sources and target logical doc on ingestion jobs

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("target_logical_doc_id", sa.String(), nullable=True),
    )
    op.create_table(
        "document_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("path_mapping", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(), nullable=False, server_default="connected"),
        sa.Column("last_scan", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("document_sources")
    op.drop_column("ingestion_jobs", "target_logical_doc_id")