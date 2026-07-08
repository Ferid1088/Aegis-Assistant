import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.crosscutting.security.password import hash_password
from rag.storage.sql.models import Role, RolePermission, User, UserRole

ADMIN_PERMISSIONS = [
    "admin:audit", "admin:conversations", "admin:departments", "admin:document_types",
    "admin:documents", "admin:roles", "admin:sources", "admin:users",
    "documents:manage_versions", "documents:upload",
]


def _admin_already_exists(db: Session) -> bool:
    """A role "is admin" if it holds every permission in ADMIN_PERMISSIONS. Checks
    each distinct role that has any permission row, in Python (not a single SQL
    query) -- this runs once at install time against a handful of roles, so a
    straightforward per-role check is clearer than a set-covering SQL query."""
    role_ids = db.execute(select(RolePermission.role_id).distinct()).scalars().all()
    for role_id in role_ids:
        granted = set(
            db.execute(select(RolePermission.permission).where(RolePermission.role_id == role_id)).scalars().all()
        )
        if set(ADMIN_PERMISSIONS).issubset(granted):
            has_user = db.execute(select(UserRole).where(UserRole.role_id == role_id)).scalar_one_or_none()
            if has_user is not None:
                return True
    return False


def _pick_username(db: Session) -> str:
    if db.execute(select(User).where(User.username == "admin")).scalar_one_or_none() is None:
        return "admin"
    return f"admin-{uuid.uuid4().hex[:8]}"


def ensure_first_admin(db: Session) -> tuple[str, str] | None:
    if _admin_already_exists(db):
        return None

    username = _pick_username(db)
    password = secrets.token_urlsafe(24)

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()

    role = Role(name="Super Admin")
    db.add(role)
    db.flush()

    for permission in ADMIN_PERMISSIONS:
        db.add(RolePermission(role_id=role.id, permission=permission))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()

    return username, password
