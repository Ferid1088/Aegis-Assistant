"""conversation_turn_verdict

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_turns",
        sa.Column("verdict", sa.String(), nullable=False, server_default="answerable"),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("assumptions", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("clarification_question", sa.String(), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("unanswerable_reason", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_turns", "unanswerable_reason")
    op.drop_column("conversation_turns", "clarification_question")
    op.drop_column("conversation_turns", "assumptions")
    op.drop_column("conversation_turns", "verdict")
