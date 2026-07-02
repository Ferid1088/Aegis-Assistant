import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, require_permission
from rag.api.schemas.admin import (
    SessionResponse, UserCreate, UserLockRequest, UserResponse, UserRoleAssign, UserUpdate,
)
from rag.crosscutting.security import session_service
from rag.crosscutting.security.audit_events import record_admin_change
from rag.crosscutting.security.password import hash_password
from rag.storage.sql.base import get_db
from rag.storage.sql.models import Department, Role, User, UserRole, UserSession

router = APIRouter()


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id), username=user.username, email=user.email,
        department_id=str(user.department_id) if user.department_id else None,
        is_active=user.is_active, mfa_enabled=user.mfa_enabled,
    )


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> UserResponse:
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="username already exists")

    department_id = None
    if body.department_id is not None:
        department_id = uuid.UUID(body.department_id)
        if db.get(Department, department_id) is None:
            raise HTTPException(status_code=404, detail="department not found")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password) if body.password else None,
        department_id=department_id,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="username already exists") from exc
    record_admin_change(str(current.user.id), "user_created", f"user:{user.id}", new_value={"username": user.username})
    return _to_response(user)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    users = db.execute(select(User)).scalars().all()
    return [_to_response(u) for u in users]


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _to_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    prev = {
        "email": user.email,
        "department_id": str(user.department_id) if user.department_id else None,
        "is_active": user.is_active,
    }

    if body.email is not None:
        user.email = body.email
    if body.department_id is not None:
        dept_id = uuid.UUID(body.department_id)
        if db.get(Department, dept_id) is None:
            raise HTTPException(status_code=404, detail="department not found")
        user.department_id = dept_id
    if body.is_active is not None:
        user.is_active = body.is_active

    db.commit()
    record_admin_change(
        str(current.user.id), "user_updated", f"user:{user.id}",
        prev_value=prev,
        new_value={
            "email": user.email,
            "department_id": str(user.department_id) if user.department_id else None,
            "is_active": user.is_active,
        },
    )
    return _to_response(user)


@router.post("/users/{user_id}/roles", status_code=201)
def assign_role(
    user_id: uuid.UUID,
    body: UserRoleAssign,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    role_id = uuid.UUID(body.role_id)
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    if db.get(UserRole, (user_id, role_id)) is not None:
        raise HTTPException(status_code=409, detail="role already assigned")

    db.add(UserRole(user_id=user_id, role_id=role_id))
    db.commit()
    record_admin_change(str(current.user.id), "user_role_assigned", f"user:{user_id}", new_value={"role_id": str(role_id)})
    return {"user_id": str(user_id), "role_id": str(role_id)}


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204)
def remove_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> None:
    ur = db.get(UserRole, (user_id, role_id))
    if ur is None:
        raise HTTPException(status_code=404, detail="role assignment not found")
    db.delete(ur)
    db.commit()
    record_admin_change(str(current.user.id), "user_role_removed", f"user:{user_id}", prev_value={"role_id": str(role_id)})


_INDEFINITE_LOCK = datetime(9999, 12, 31, tzinfo=timezone.utc)


@router.post("/users/{user_id}/lock", status_code=204)
def lock_user(
    user_id: uuid.UUID,
    body: UserLockRequest,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.locked_until = _INDEFINITE_LOCK
    user.lock_reason = body.reason
    db.commit()
    record_admin_change(str(current.user.id), "user_locked", f"user:{user_id}", new_value={"reason": body.reason})


@router.post("/users/{user_id}/unlock", status_code=204)
def unlock_user(
    user_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.locked_until = None
    user.lock_reason = None
    user.failed_login_count = 0
    db.commit()
    record_admin_change(str(current.user.id), "user_unlocked", f"user:{user_id}")


@router.get("/users/{user_id}/sessions", response_model=list[SessionResponse])
def list_sessions(
    user_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> list[SessionResponse]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    sessions = db.execute(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ).scalars().all()
    return [
        SessionResponse(
            id=str(s.id), issued_at=s.issued_at.isoformat(), expires_at=s.expires_at.isoformat(),
            ip=s.ip, user_agent=s.user_agent,
        )
        for s in sessions
    ]


@router.delete("/users/{user_id}/sessions", status_code=200)
def revoke_all_user_sessions(
    user_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    count = session_service.revoke_all_sessions(db, user_id, str(current.user.id))
    record_admin_change(str(current.user.id), "user_sessions_revoked", f"user:{user_id}", new_value={"count": count})
    return {"revoked_count": count}
