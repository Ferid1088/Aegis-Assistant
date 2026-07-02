from fastapi import APIRouter, Depends, Query

from rag.api.deps import AuthenticatedUser, require_permission
from rag.api.schemas.admin import AuditEntryResponse, AuditVerifyResponse
from rag.config import settings
from rag.crosscutting.security.audit import AuditLog

router = APIRouter()


@router.get("/audit", response_model=list[AuditEntryResponse])
def list_audit_entries(
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    current: AuthenticatedUser = Depends(require_permission("admin:audit")),
) -> list[AuditEntryResponse]:
    log = AuditLog(log_dir=settings.audit_log_dir)
    entries = log.read_all()

    if actor is not None:
        entries = [e for e in entries if e.get("actor_user") == actor]
    if action is not None:
        entries = [e for e in entries if e.get("action") == action]
    if resource is not None:
        entries = [e for e in entries if e.get("resource") == resource]

    return [
        AuditEntryResponse(
            actor_user=e.get("actor_user", ""), action=e.get("action", ""),
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
