"""Central authorization engine — ONE boolean, applied everywhere.

Access(user, resource, action) = ALLOW iff ALL hold (AND, short-circuit to DENY):
  1. TENANT:     resource.tenant_id == user.tenant_id (or break-glass)
  2. NO DENY:    no explicit DENY rule matches
  3. ROLE:       user's roles grant the action
  4. CLEARANCE:  user_levels ∩ resource.acl_levels ≠ ∅ AND acl_levels ≠ []  (05.1 INV-1/2)
  5. STATE:      resource state allows the action (conversation lifecycle)
  6. OWNERSHIP:  for owned resources: owner == user OR explicit grant exists

document_type is NOT in this boolean (relevance, not security).
Explicit DENY always overrides any ALLOW.
Default = DENY.
"""

from dataclasses import dataclass, field

from rag.config import settings


@dataclass
class AuthSubject:
    user_id: str
    tenant_id: str = "default"
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    effective_levels: list[str] = field(default_factory=list)
    deny_rules: list[str] = field(default_factory=list)
    is_break_glass: bool = False


@dataclass
class AuthResource:
    resource_id: str
    tenant_id: str = "default"
    acl_levels: list[str] = field(default_factory=list)
    owner_id: str | None = None
    state: str = "active"
    granted_users: list[str] = field(default_factory=list)


@dataclass
class AuthResult:
    allowed: bool
    denied_at: str | None = None
    reason: str = ""


def authorize(subject: AuthSubject, resource: AuthResource, action: str) -> AuthResult:
    if not settings.acl_enforce:
        return AuthResult(allowed=True, reason="enforcement disabled")

    # 1. TENANT
    if resource.tenant_id != subject.tenant_id:
        if not subject.is_break_glass:
            return AuthResult(allowed=False, denied_at="tenant", reason="cross-tenant access denied")

    # 2. NO DENY
    if action in subject.deny_rules or f"{action}:{resource.resource_id}" in subject.deny_rules:
        return AuthResult(allowed=False, denied_at="deny_rule", reason="explicit DENY rule matched")

    # 3. ROLE
    if action not in subject.permissions:
        return AuthResult(allowed=False, denied_at="role", reason=f"no permission for '{action}'")

    # 4. CLEARANCE (05.1 INV-1 + INV-2)
    if not resource.acl_levels:
        return AuthResult(allowed=False, denied_at="clearance", reason="resource has no acl_levels (INV-1: default deny)")
    if not subject.effective_levels:
        return AuthResult(allowed=False, denied_at="clearance", reason="user has no effective levels")
    if not set(subject.effective_levels) & set(resource.acl_levels):
        return AuthResult(allowed=False, denied_at="clearance", reason="clearance insufficient (INV-2: no intersection)")

    # 5. STATE
    blocked_actions = _state_blocked_actions(resource.state)
    if action in blocked_actions:
        return AuthResult(allowed=False, denied_at="state",
                          reason=f"action '{action}' blocked in state '{resource.state}'")

    # 6. OWNERSHIP
    if resource.owner_id is not None:
        if subject.user_id != resource.owner_id and subject.user_id not in resource.granted_users:
            return AuthResult(allowed=False, denied_at="ownership", reason="not owner and no explicit grant")

    return AuthResult(allowed=True, reason="all checks passed")


def _state_blocked_actions(state: str) -> set[str]:
    if state == "locked":
        return {"modify", "delete", "rename", "append"}
    if state == "soft_deleted":
        return {"modify", "rename", "append", "search"}
    if state == "purged":
        return {"read", "modify", "delete", "rename", "append", "search", "restore"}
    return set()
