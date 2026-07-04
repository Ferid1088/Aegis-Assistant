import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.config import settings
from rag.crosscutting.security import audit_events
from rag.crosscutting.security.lockout import apply_failed_attempt, is_locked
from rag.crosscutting.security.mfa import decrypt_secret, verify_totp
from rag.crosscutting.security.password import verify_password
from rag.crosscutting.security.time_utils import as_aware_utc
from rag.crosscutting.security.tokens import create_access_token, create_mfa_pending_token, decode_token, generate_refresh_token
from rag.storage.sql.models import LoginAttempt, RefreshToken, User, UserSession


class AuthError(Exception):
    """Message is always safe to show the caller (never leaks account existence)."""


@dataclass
class LoginResult:
    mfa_required: bool
    mfa_pending_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None


def login(db: Session, username: str, password: str, ip: str = "", request_id: str = "") -> LoginResult:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()

    if user is None or not user.is_active or user.password_hash is None:
        _record_attempt(db, None, username, False, ip)
        audit_events.record_login_failure(username, request_id=request_id, ip=ip)
        raise AuthError("invalid username or password")

    if is_locked(as_aware_utc(user.locked_until)):
        _record_attempt(db, user.id, username, False, ip)
        raise AuthError(f"account locked: {user.lock_reason}")

    if not verify_password(password, user.password_hash):
        _record_attempt(db, user.id, username, False, ip)
        audit_events.record_login_failure(username, request_id=request_id, ip=ip)
        _apply_lockout(db, user, request_id)
        raise AuthError("invalid username or password")

    user.failed_login_count = 0
    _record_attempt(db, user.id, username, True, ip)
    db.commit()
    audit_events.record_login_success(str(user.id), request_id=request_id, ip=ip)

    if user.mfa_enabled:
        return LoginResult(mfa_required=True, mfa_pending_token=create_mfa_pending_token(str(user.id)))

    return _issue_tokens(db, user, ip)


def verify_mfa(db: Session, mfa_pending_token: str, totp_code: str, ip: str = "") -> LoginResult:
    try:
        payload = decode_token(mfa_pending_token)
    except Exception as exc:
        raise AuthError("invalid or expired MFA token") from exc

    if payload.get("type") != "mfa_pending":
        raise AuthError("invalid MFA token")

    user = db.execute(select(User).where(User.id == uuid.UUID(payload["sub"]))).scalar_one_or_none()
    if user is None or not user.mfa_enabled or user.mfa_secret_encrypted is None:
        raise AuthError("MFA not enabled for this account")

    try:
        raw_secret = decrypt_secret(db, user.mfa_secret_encrypted)
    except ValueError as exc:
        raise AuthError("MFA verification failed") from exc
    if not verify_totp(raw_secret, totp_code):
        raise AuthError("invalid MFA code")

    return _issue_tokens(db, user, ip)


def _record_attempt(db: Session, user_id: uuid.UUID | None, username: str, success: bool, ip: str) -> None:
    db.add(LoginAttempt(user_id=user_id, username_tried=username, success=success, ip=ip))
    db.commit()


def _apply_lockout(db: Session, user: User, request_id: str) -> None:
    new_count, locked_until, lock_reason = apply_failed_attempt(user.failed_login_count)
    user.failed_login_count = new_count
    user.last_failed_login_at = datetime.now(timezone.utc)
    if locked_until is not None:
        user.locked_until = locked_until
        user.lock_reason = lock_reason
        db.commit()
        audit_events.record_account_locked(str(user.id), lock_reason, request_id=request_id)
    else:
        db.commit()


def _issue_tokens(db: Session, user: User, ip: str) -> LoginResult:
    now = datetime.now(timezone.utc)
    session = UserSession(
        user_id=user.id, issued_at=now,
        expires_at=now + timedelta(seconds=settings.jwt_refresh_ttl_seconds), ip=ip,
    )
    db.add(session)
    db.flush()

    raw_refresh, refresh_hash = generate_refresh_token()
    db.add(RefreshToken(
        session_id=session.id, user_id=user.id, token_hash=refresh_hash,
        issued_at=now, expires_at=now + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
    ))
    db.commit()

    access = create_access_token(str(user.id), str(session.id), user.token_version)
    return LoginResult(mfa_required=False, access_token=access, refresh_token=raw_refresh)
