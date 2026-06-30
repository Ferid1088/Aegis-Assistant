"""manage_versions permission + audit wiring for the logical/version layer (02.1 §2.4).

Plain upload != version management. Declaring an upload a new version of an existing
document, activating/deactivating a version, or relinking a version all require the
manage_versions permission and are audited (05.2), reusing the existing authorize()
boolean and hash-chained AuditLog — no new security machinery.
"""

from rag.crosscutting.security.audit import AuditEntry, AuditLog
from rag.crosscutting.security.authorize import AuthResource, AuthResult, AuthSubject, authorize

MANAGE_VERSIONS = "manage_versions"


def authorize_version_action(
    subject: AuthSubject,
    resource: AuthResource,
    action: str,
    audit_log: AuditLog,
    **audit_fields: object,
) -> AuthResult:
    """Gate a version-management action and audit every attempt, allowed or denied."""
    result = authorize(subject, resource, action)
    audit_log.append(AuditEntry(
        actor_user=subject.user_id,
        action=action,
        resource=resource.resource_id,
        tenant_id=subject.tenant_id,
        metadata={"allowed": result.allowed, "reason": result.reason, **audit_fields},
    ))
    return result
