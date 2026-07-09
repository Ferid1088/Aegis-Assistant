import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, require_permission
from rag.api.schemas.admin import AuditEntryResponse, AuditVerifyResponse
from rag.config import settings
from rag.crosscutting.security.audit import AuditLog
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import User

router = APIRouter()


def _resolve_actor_usernames(db: Session, actor_ids: set[str]) -> dict[str, str]:
    """actor_user in the audit log is a raw user id for most actions (immutable,
    hash-chained entries never store display names) -- resolve id -> username here
    for display. record_login_failure() is the one exception: it stores the
    attempted username string directly (there's no user id yet), which is already
    human-readable and not a UUID at all, so those are left out of this map
    entirely rather than mislabeled "(deleted user)"."""
    valid_ids = []
    for actor_id in actor_ids:
        try:
            valid_ids.append(uuid.UUID(actor_id))
        except ValueError:
            continue
    if not valid_ids:
        return {}
    users = db.execute(select(User).where(User.id.in_(valid_ids))).scalars().all()
    found = {str(u.id): u.username for u in users}
    # A valid UUID with no matching user = a genuinely deleted account, distinct
    # from a non-UUID actor_user (e.g. failed-login username attempts) which
    # should just display as-is, not be relabeled.
    return {str(uid): found.get(str(uid), "(deleted user)") for uid in valid_ids}


@router.get("/audit", response_model=list[AuditEntryResponse])
def list_audit_entries(
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    current: AuthenticatedUser = Depends(require_permission("admin:audit")),
    db: Session = Depends(get_db),
) -> list[AuditEntryResponse]:
    log = AuditLog(log_dir=settings.audit_log_dir)
    entries = log.read_all()

    if actor is not None:
        entries = [e for e in entries if e.get("actor_user") == actor]
    if action is not None:
        entries = [e for e in entries if e.get("action") == action]
    if resource is not None:
        entries = [e for e in entries if e.get("resource") == resource]

    usernames = _resolve_actor_usernames(db, {e.get("actor_user", "") for e in entries})

    return [
        AuditEntryResponse(
            actor_user=e.get("actor_user", ""),
            actor_username=usernames.get(e.get("actor_user", "")),
            action=e.get("action", ""),
            resource=e.get("resource", ""), ts=e.get("ts", ""),
            request_id=e.get("request_id", ""),
            prev_value=e.get("prev_value"), new_value=e.get("new_value"),
        )
        for e in entries
    ]


@router.get("/audit/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(
    current: AuthenticatedUser = Depends(require_permission("admin:audit")),
) -> AuditVerifyResponse:
    log = AuditLog(log_dir=settings.audit_log_dir)
    valid, count, error = log.verify_chain()
    return AuditVerifyResponse(valid=valid, count=count, error=error)
