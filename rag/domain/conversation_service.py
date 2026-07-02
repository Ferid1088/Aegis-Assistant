import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.domain.conversation import (
    Conversation as DomainConversation, ConversationState, resolve_erasure, transition as domain_transition,
)
from rag.storage.sql.models import Conversation


class ConversationNotFound(Exception):
    pass


def create_conversation(db: Session, owner_id: uuid.UUID) -> Conversation:
    conv = Conversation(owner_id=owner_id, state=ConversationState.ACTIVE.value)
    db.add(conv)
    db.commit()
    return conv


def get_conversation(db: Session, conversation_id: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise ConversationNotFound()
    return conv


def get_owned_conversation(db: Session, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.owner_id != owner_id:
        raise ConversationNotFound()
    return conv


def list_owned_conversations(db: Session, owner_id: uuid.UUID) -> list[Conversation]:
    return list(db.execute(select(Conversation).where(Conversation.owner_id == owner_id)).scalars().all())


class TransitionError(Exception):
    pass


def _to_domain(conv: Conversation) -> DomainConversation:
    return DomainConversation(
        conversation_id=str(conv.id),
        owner_id=str(conv.owner_id),
        state=ConversationState(conv.state),
        legal_hold=conv.legal_hold,
        erasure_requested=conv.erasure_requested,
        retention_days=conv.retention_days,
        encryption_key_id=conv.encryption_key_id,
    )


def transition_conversation(db: Session, conv: Conversation, target_state: ConversationState) -> Conversation:
    domain_conv = _to_domain(conv)
    success, reason = domain_transition(domain_conv, target_state)
    if not success:
        raise TransitionError(reason)

    conv.state = domain_conv.state.value
    db.commit()
    return conv


def set_legal_hold(db: Session, conv: Conversation, hold: bool) -> Conversation:
    conv.legal_hold = hold
    db.commit()
    return conv


def request_erasure(db: Session, conv: Conversation) -> tuple[str, str]:
    conv.erasure_requested = True
    db.commit()

    domain_conv = _to_domain(conv)
    action, reason = resolve_erasure(domain_conv)

    if action == "purge":
        from rag.domain import conversation_turn_service
        conversation_turn_service.delete_all_for_conversation(db, conv.id)
        conv.state = ConversationState.PURGED.value
        conv.encryption_key_id = None
        db.commit()

    return action, reason
