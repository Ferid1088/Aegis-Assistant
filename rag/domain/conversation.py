"""Conversation lifecycle — explicit state machine.

States: ACTIVE → ARCHIVED / LOCKED / SOFT_DELETED → PURGED (terminal)
Orthogonal flags: legal_hold, retention_policy, erasure_requested

Erasure precedence (§4.2):
  1. LEGAL HOLD overrides everything (Art. 17(3)(e))
  2. ERASURE REQUEST overrides retention + soft-delete (forces hard purge/crypto-shred)
  3. RETENTION POLICY — ordinary automated lifecycle
  4. SOFT-DELETE — default user action, reversible
"""

from dataclasses import dataclass, field
from enum import Enum


class ConversationState(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    LOCKED = "locked"
    SOFT_DELETED = "soft_deleted"
    PURGED = "purged"


VALID_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.ACTIVE: {ConversationState.ARCHIVED, ConversationState.LOCKED, ConversationState.SOFT_DELETED},
    ConversationState.ARCHIVED: {ConversationState.ACTIVE, ConversationState.SOFT_DELETED},
    ConversationState.LOCKED: {ConversationState.ACTIVE},
    ConversationState.SOFT_DELETED: {ConversationState.ACTIVE, ConversationState.PURGED},
    ConversationState.PURGED: set(),
}


class ErasurePrecedence(str, Enum):
    LEGAL_HOLD = "legal_hold"
    ERASURE_REQUEST = "erasure_request"
    RETENTION_POLICY = "retention_policy"
    SOFT_DELETE = "soft_delete"


@dataclass
class Conversation:
    conversation_id: str
    tenant_id: str = "default"
    owner_id: str = ""
    state: ConversationState = ConversationState.ACTIVE
    legal_hold: bool = False
    erasure_requested: bool = False
    retention_days: int | None = None
    encryption_key_id: str | None = None
    granted_users: list[str] = field(default_factory=list)


def can_transition(current: ConversationState, target: ConversationState) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())


def transition(conversation: Conversation, target: ConversationState) -> tuple[bool, str]:
    if not can_transition(conversation.state, target):
        return False, f"invalid transition: {conversation.state.value} → {target.value}"

    if target == ConversationState.PURGED and conversation.legal_hold:
        return False, "cannot purge: legal hold active (Art. 17(3)(e))"

    conversation.state = target
    return True, f"transitioned to {target.value}"


def resolve_erasure(conversation: Conversation) -> tuple[str, str]:
    """Resolve erasure precedence. Returns (action, reason)."""
    if conversation.legal_hold:
        return "refuse", "legal hold active — erasure refused (Art. 17(3)(e)), logged with legal basis"

    if conversation.erasure_requested:
        return "purge", "erasure requested — crypto-shred/hard purge required (Art. 17)"

    if conversation.retention_days is not None:
        return "retain", f"retention policy: {conversation.retention_days} days"

    if conversation.state == ConversationState.SOFT_DELETED:
        return "keep_soft_deleted", "soft-deleted, reversible, no erasure requested"

    return "none", "no erasure action needed"
