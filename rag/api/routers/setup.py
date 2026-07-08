from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rag.api.schemas.setup import SetupAdminCreate, SetupStatusResponse
from rag.crosscutting.security.audit_events import record_admin_change
from rag.crosscutting.security.password import hash_password
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole

router = APIRouter()

ADMIN_PERMISSIONS = [
    "admin:audit", "admin:conversations", "admin:departments", "admin:document_types",
    "admin:documents", "admin:roles", "admin:sources", "admin:users",
    "documents:manage_versions", "documents:upload",
]

MIN_PASSWORD_LENGTH = 12


def _admin_already_exists(db: Session) -> bool:
    """A role "is admin" if it holds every permission in ADMIN_PERMISSIONS. Checks
    each distinct role that has any permission row, in Python (not a single SQL
    query) -- this runs on every unauthenticated /status poll plus once per /admin
    submission, both low-volume, so a straightforward per-role check is clearer
    than a set-covering SQL query."""
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


@router.get("/status", response_model=SetupStatusResponse)
def get_setup_status(db: Session = Depends(get_db)) -> SetupStatusResponse:
    return SetupStatusResponse(needs_setup=not _admin_already_exists(db))


@router.post("/admin", status_code=201)
def create_setup_admin(body: SetupAdminCreate, db: Session = Depends(get_db)) -> dict:
    if _admin_already_exists(db):
        raise HTTPException(status_code=409, detail="setup already completed")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()

    role = Role(name="Super Admin")
    db.add(role)
    db.flush()

    for permission in ADMIN_PERMISSIONS:
        db.add(RolePermission(role_id=role.id, permission=permission))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="username already exists") from exc

    record_admin_change(
        "setup-wizard", "create_first_admin", f"user:{user.id}", new_value={"username": user.username},
    )
    return {"ok": True}
