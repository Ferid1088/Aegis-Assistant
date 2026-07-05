import uuid

import pytest

from rag.domain import conversation_service
from rag.domain.conversation import ConversationState
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


def test_transition_conversation_to_valid_state_succeeds(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)

    updated = conversation_service.transition_conversation(db_session, conv, ConversationState.ARCHIVED)

    assert updated.state == "archived"


def test_transition_conversation_to_invalid_state_raises(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)
    conversation_service.transition_conversation(db_session, conv, ConversationState.SOFT_DELETED)
    conversation_service.transition_conversation(db_session, conv, ConversationState.PURGED)
    # PURGED is terminal — no transitions allowed out of it, not even back to ACTIVE

    with pytest.raises(conversation_service.TransitionError):
        conversation_service.transition_conversation(db_session, conv, ConversationState.ACTIVE)


def test_transition_to_purged_blocked_by_legal_hold(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)
    conversation_service.transition_conversation(db_session, conv, ConversationState.SOFT_DELETED)
    conv.legal_hold = True
    db_session.commit()

    with pytest.raises(conversation_service.TransitionError):
        conversation_service.transition_conversation(db_session, conv, ConversationState.PURGED)


def test_set_legal_hold_toggles_flag(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)

    updated = conversation_service.set_legal_hold(db_session, conv, True)
    assert updated.legal_hold is True

    updated = conversation_service.set_legal_hold(db_session, conv, False)
    assert updated.legal_hold is False


def test_request_erasure_purges_when_no_legal_hold(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)
    conversation_service.transition_conversation(db_session, conv, ConversationState.SOFT_DELETED)

    action, reason = conversation_service.request_erasure(db_session, conv)

    assert action == "purge"
    assert conv.state == "purged"
    assert conv.erasure_requested is True
    assert conv.encryption_key_id is None


def test_request_erasure_refused_under_legal_hold(db_session):
    owner = _make_user(db_session)
    conv = conversation_service.create_conversation(db_session, owner.id)
    conversation_service.set_legal_hold(db_session, conv, True)

    action, reason = conversation_service.request_erasure(db_session, conv)

    assert action == "refuse"
    assert "legal hold" in reason.lower()
    assert conv.state == "active"
    assert conv.erasure_requested is True


def test_request_erasure_purge_deletes_conversation_turns(db_session):
    from rag.domain import conversation_service, conversation_turn_service
    from rag.storage.sql.models import User

    user = User(username="alice")
    db_session.add(user)
    db_session.flush()
    conv = conversation_service.create_conversation(db_session, user.id)
    conversation_turn_service.append_turn(
        db_session, conv.id, question="q", standalone_question="q", answer="a", citations=[],
    )
    conversation_service.transition_conversation(
        db_session, conv, conversation_service.ConversationState.SOFT_DELETED,
    )

    conversation_service.request_erasure(db_session, conv)

    assert conversation_turn_service.list_recent_turns(db_session, conv.id, limit=10) == []


def test_create_conversation_generates_real_keystore_key(db_session):
    from rag.crosscutting.security import keystore
    from rag.domain import conversation_service
    from rag.storage.sql.models import User

    user = User(username="alice")
    db_session.add(user)
    db_session.flush()

    conv = conversation_service.create_conversation(db_session, user.id)

    assert conv.encryption_key_id == f"conversation:{conv.id}"
    key = keystore.get_or_create_key(db_session, conv.encryption_key_id)
    assert len(key) > 0


def test_request_erasure_purge_deletes_keystore_key(db_session):
    from rag.crosscutting.security import keystore
    from rag.domain import conversation_service
    from rag.storage.sql.models import User

    user = User(username="alice")
    db_session.add(user)
    db_session.flush()
    conv = conversation_service.create_conversation(db_session, user.id)
    purpose = conv.encryption_key_id
    original_key = keystore.get_or_create_key(db_session, purpose)

    conversation_service.transition_conversation(
        db_session, conv, conversation_service.ConversationState.SOFT_DELETED,
    )
    conversation_service.request_erasure(db_session, conv)

    new_key = keystore.get_or_create_key(db_session, purpose)
    assert new_key != original_key
