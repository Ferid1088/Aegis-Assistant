import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.config import settings
from rag.crosscutting.security.audit_events import record_session_revoked
from rag.crosscutting.security.time_utils import as_aware_utc
from rag.crosscutting.security.tokens import create_access_token, generate_refresh_token, hash_refresh_token
from rag.storage.sql.models import RefreshToken, User, UserSession


class SessionError(Exception):
    pass


def refresh(db: Session, raw_refresh_token: str) -> tuple[str, str]:
    token_hash = hash_refresh_token(raw_refresh_token)
    token = db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).scalar_one_or_none()

    if token is None or token.revoked_at is not None:
        raise SessionError("refresh token invalid or already used")
    if as_aware_utc(token.expires_at) < datetime.now(timezone.utc):
        raise SessionError("refresh token expired")

    session = db.execute(select(UserSession).where(UserSession.id == token.session_id)).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise SessionError("session revoked")

    user = db.execute(select(User).where(User.id == token.user_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise SessionError("account inactive")

    now = datetime.now(timezone.utc)
    new_raw, new_hash = generate_refresh_token()
    new_token = RefreshToken(
        session_id=session.id, user_id=user.id, token_hash=new_hash,
        issued_at=now, expires_at=now + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
    )
    db.add(new_token)
    db.flush()

    token.revoked_at = now
    token.replaced_by = new_token.id
    db.commit()

    new_access = create_access_token(str(user.id), str(session.id), user.token_version)
    return new_access, new_raw


def logout(db: Session, session_id: str, actor_user: str, request_id: str = "") -> None:
    session = db.execute(select(UserSession).where(UserSession.id == uuid.UUID(session_id))).scalar_one_or_none()
    if session is None:
        raise SessionError("session not found")

    now = datetime.now(timezone.utc)
    session.revoked_at = now
    db.execute(
        RefreshToken.__table__.update()
        .where(RefreshToken.session_id == session.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()
    record_session_revoked(actor_user, session_id, request_id=request_id)


def revoke_all_sessions(db: Session, user_id: uuid.UUID, actor_user: str, request_id: str = "") -> int:
    """Revokes every non-revoked session for a user, their refresh tokens, and bumps
    token_version so any already-issued access token is invalidated too.
    Returns the number of sessions revoked."""
    now = datetime.now(timezone.utc)
    sessions = db.execute(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ).scalars().all()

    for session in sessions:
        session.revoked_at = now
        db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.session_id == session.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    user = db.get(User, user_id)
    if user is not None:
        user.token_version += 1

    db.commit()
    for session in sessions:
        record_session_revoked(actor_user, str(session.id), request_id=request_id)

    return len(sessions)
