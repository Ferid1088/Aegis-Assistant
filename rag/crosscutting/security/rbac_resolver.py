"""RBAC resolver — derives a fresh AuthSubject from the database on every call.

Deliberately uncached: RBAC changes (role/permission/access-level edits) take
effect on the very next request with no cache-invalidation logic required.
Do not add caching here.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.crosscutting.security.authorize import AuthSubject
from rag.infra.stores.sql.models import AccessLevel, Role, RoleAccessGrant, RolePermission, User, UserRole


def resolve_auth_subject(db: Session, user: User) -> AuthSubject:
    role_rows = db.execute(
        select(Role.id, Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
    ).all()
    role_ids = [row.id for row in role_rows]
    role_names = [row.name for row in role_rows]

    permissions: list[str] = []
    levels: list[str] = []
    if role_ids:
        permissions = list(
            db.execute(
                select(RolePermission.permission).where(RolePermission.role_id.in_(role_ids))
            ).scalars().all()
        )
        levels = list(
            db.execute(
                select(AccessLevel.label)
                .join(RoleAccessGrant, RoleAccessGrant.access_level_id == AccessLevel.id)
                .where(RoleAccessGrant.role_id.in_(role_ids))
            ).scalars().all()
        )

    return AuthSubject(
        user_id=str(user.id),
        tenant_id="default",
        roles=role_names,
        permissions=list(dict.fromkeys(permissions)),
        effective_levels=list(dict.fromkeys(levels)),
        deny_rules=[],
    )
