"""Typed audit event helpers over the hash-chained AuditLog.

Each function creates a fresh AuditLog instance per call (not a module-level singleton)
so that each write re-reads the last hash from disk — correct under multiple worker
processes, at the cost of an O(n) file read per audit event. This is acceptable at
auth/RBAC event volume.
"""

from rag.config import settings
from rag.crosscutting.security.audit import AuditEntry, AuditLog


def _log() -> AuditLog:
    """Return a fresh AuditLog instance per call (not a module-level singleton)."""
    return AuditLog(log_dir=settings.audit_log_dir)


def record_login_success(user_id: str, request_id: str = "", ip: str = "") -> None:
    """Record a successful login."""
    _log().append(
        AuditEntry(
            actor_user=user_id,
            action="login_success",
            resource=f"user:{user_id}",
            request_id=request_id,
            ip=ip,
        )
    )


def record_login_failure(username_tried: str, request_id: str = "", ip: str = "") -> None:
    """Record a failed login attempt."""
    _log().append(
        AuditEntry(
            actor_user=username_tried,
            action="login_failure",
            resource=f"user:{username_tried}",
            request_id=request_id,
            ip=ip,
        )
    )


def record_account_locked(user_id: str, reason: str, request_id: str = "") -> None:
    """Record an account being locked."""
    _log().append(
        AuditEntry(
            actor_user=user_id,
            action="account_locked",
            resource=f"user:{user_id}",
            new_value={"reason": reason},
            request_id=request_id,
        )
    )


def record_account_unlocked(actor_user: str, target_user_id: str, request_id: str = "") -> None:
    """Record an account being unlocked by an admin."""
    _log().append(
        AuditEntry(
            actor_user=actor_user,
            action="account_unlocked",
            resource=f"user:{target_user_id}",
            request_id=request_id,
        )
    )


def record_mfa_enrolled(user_id: str, request_id: str = "") -> None:
    """Record MFA enrollment."""
    _log().append(
        AuditEntry(
            actor_user=user_id,
            action="mfa_enrolled",
            resource=f"user:{user_id}",
            request_id=request_id,
        )
    )


def record_session_revoked(actor_user: str, session_id: str, request_id: str = "") -> None:
    """Record a session being revoked."""
    _log().append(
        AuditEntry(
            actor_user=actor_user,
            action="session_revoked",
            resource=f"session:{session_id}",
            request_id=request_id,
        )
    )


def record_admin_change(
    actor_user: str,
    action: str,
    resource: str,
    prev_value: dict | None = None,
    new_value: dict | None = None,
    request_id: str = "",
) -> None:
    """Record an admin change (user lock, permission change, etc.)."""
    _log().append(
        AuditEntry(
            actor_user=actor_user,
            action=action,
            resource=resource,
            prev_value=prev_value,
            new_value=new_value,
            request_id=request_id,
        )
    )
