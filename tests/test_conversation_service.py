import uuid

import pytest

from rag.domain import conversation_service
from rag.storage.sql.models import Conversation, User


def _make_user(db_session, username="alice"):
    user = User(username=username)
    db_session.add(user)
    db_session.commit()
    return user


def test_create_conversation_defaults_to_active(db_session):
    owner = _make_user(db_session)

    conv = conversation_service.create_conversation(db_session, owner.id)

    assert conv.owner_id == owner.id
    assert conv.state == "active"
    assert conv.legal_hold is False


def test_get_owned_conversation_succeeds_for_owner(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)

    fetched = conversation_service.get_owned_conversation(db_session, conv.id, owner.id)

    assert fetched.id == conv.id


def test_get_owned_conversation_raises_for_non_owner(db_session):
    owner = _make_user(db_session, "alice")
    other = _make_user(db_session, "mallory")
    conv = conversation_service.create_conversation(db_session, owner.id)

    with pytest.raises(conversation_service.ConversationNotFound):
        conversation_service.get_owned_conversation(db_session, conv.id, other.id)


def test_get_owned_conversation_raises_for_unknown_id(db_session):
    owner = _make_user(db_session)

    with pytest.raises(conversation_service.ConversationNotFound):
        conversation_service.get_owned_conversation(db_session, uuid.uuid4(), owner.id)


def test_get_conversation_ignores_ownership(db_session):
    owner = _make_user(db_session, "alice")
    conv = conversation_service.create_conversation(db_session, owner.id)

    fetched = conversation_service.get_conversation(db_session, conv.id)

    assert fetched.id == conv.id


def test_list_owned_conversations_returns_only_owners(db_session):
    owner = _make_user(db_session, "alice")
    other = _make_user(db_session, "mallory")
    conversation_service.create_conversation(db_session, owner.id)
    conversation_service.create_conversation(db_session, owner.id)
    conversation_service.create_conversation(db_session, other.id)

    owned = conversation_service.list_owned_conversations(db_session, owner.id)

    assert len(owned) == 2
    assert all(c.owner_id == owner.id for c in owned)
