import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.crosscutting.security.authorize import AuthSubject
from rag.crosscutting.security.rbac_resolver import resolve_auth_subject
from rag.crosscutting.security.tokens import decode_token
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import User, UserSession


@dataclass
class AuthenticatedUser:
    user: User
    session_id: uuid.UUID
    auth_subject: AuthSubject


def _parse_uuid_claim(value: str | None) -> uuid.UUID:
    if value is None:
        raise HTTPException(status_code=401, detail="invalid token")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthenticatedUser:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth_header.removeprefix("Bearer ")

    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="invalid token type")

    user_id = _parse_uuid_claim(payload.get("sub"))
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="account inactive")

    if payload.get("tv") != user.token_version:
        raise HTTPException(status_code=401, detail="token has been invalidated")

    session_id = _parse_uuid_claim(payload.get("session_id"))
    session = db.execute(select(UserSession).where(UserSession.id == session_id)).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="session revoked")

    auth_subject = resolve_auth_subject(db, user)
    return AuthenticatedUser(user=user, session_id=session_id, auth_subject=auth_subject)


def require_permission(permission: str):
    def _check(current: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if permission not in current.auth_subject.permissions:
            raise HTTPException(status_code=403, detail=f"missing permission: {permission}")
        return current
    return _check
