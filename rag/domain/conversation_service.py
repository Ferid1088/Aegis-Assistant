import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.domain.conversation import ConversationState
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
