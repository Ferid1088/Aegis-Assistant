"""title/department/document_type/access_level on ingestion jobs

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
    op.add_column("ingestion_jobs", sa.Column("title", sa.String(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("department_id", sa.String(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("document_type_id", sa.String(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("access_level_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "access_level_ids")
    op.drop_column("ingestion_jobs", "document_type_id")
    op.drop_column("ingestion_jobs", "department_id")
    op.drop_column("ingestion_jobs", "title")
