"""initial auth/RBAC schema

Revision ID: 0001
Revises:
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
    )
    op.create_table(
        "document_types",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(), nullable=False, unique=True),
    )
    op.create_table(
        "access_levels",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("department_id", sa.Uuid(as_uuid=True), sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.UniqueConstraint("department_id", "label", name="uq_access_level_dept_label"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("email", sa.String(), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("department_id", sa.Uuid(as_uuid=True), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_reason", sa.String(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "role_access_grants",
        sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("access_level_id", sa.Uuid(as_uuid=True), sa.ForeignKey("access_levels.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("granted_by", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission", sa.String(), primary_key=True),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "sso_identities",
        sa.Column("provider", sa.String(), primary_key=True),
        sa.Column("external_id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("username_tried", sa.String(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("login_attempts")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("sso_identities")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("role_access_grants")
    op.drop_table("users")
    op.drop_table("access_levels")
    op.drop_table("document_types")
    op.drop_table("roles")
    op.drop_table("departments")
