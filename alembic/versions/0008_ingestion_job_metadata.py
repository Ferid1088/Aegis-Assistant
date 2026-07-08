"""ingestion job metadata: department, document_type, access_level

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("department", sa.String(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("document_type", sa.String(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("access_level", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "access_level")
    op.drop_column("ingestion_jobs", "document_type")
    op.drop_column("ingestion_jobs", "department")
