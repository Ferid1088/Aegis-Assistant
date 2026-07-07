from rag.domain import conversation_turn_service
from rag.storage.sql.models import Conversation, User


def _make_conversation(db_session):
    user = User(username="alice")
    db_session.add(user)
    db_session.flush()
    conv = Conversation(owner_id=user.id)
    db_session.add(conv)
    db_session.commit()
    return conv


def test_append_turn_assigns_sequential_index(db_session):
    conv = _make_conversation(db_session)
    t1 = conversation_turn_service.append_turn(
        db_session, conv.id, question="q1", standalone_question="q1", answer="a1", citations=[],
    )
    t2 = conversation_turn_service.append_turn(
        db_session, conv.id, question="q2", standalone_question="q2", answer="a2", citations=[],
    )
    assert t1.turn_index == 1
    assert t2.turn_index == 2


def test_list_recent_turns_respects_limit_and_order(db_session):
    conv = _make_conversation(db_session)
    for i in range(5):
        conversation_turn_service.append_turn(
            db_session, conv.id, question=f"q{i}", standalone_question=f"q{i}", answer=f"a{i}", citations=[],
        )
    recent = conversation_turn_service.list_recent_turns(db_session, conv.id, limit=2)
    assert [t.question for t in recent] == ["q3", "q4"]


def test_delete_all_for_conversation_removes_rows(db_session):
    conv = _make_conversation(db_session)
    conversation_turn_service.append_turn(
        db_session, conv.id, question="q1", standalone_question="q1", answer="a1", citations=[],
    )
    conversation_turn_service.delete_all_for_conversation(db_session, conv.id)
    assert conversation_turn_service.list_recent_turns(db_session, conv.id, limit=10) == []


def test_to_turn_history_matches_finalize_turn_key_shape(db_session):
    conv = _make_conversation(db_session)
    conversation_turn_service.append_turn(
        db_session, conv.id, question="q1", standalone_question="sq1", answer="a1", citations=[],
    )
    turns = conversation_turn_service.list_recent_turns(db_session, conv.id, limit=10)

    history = conversation_turn_service.to_turn_history(turns)

    assert history == [{"user_question": "q1", "standalone_question": "sq1", "answer": "a1"}]


def test_append_turn_persists_verdict_fields(db_session):
    conv = _make_conversation(db_session)
    turn = conversation_turn_service.append_turn(
        db_session, conv.id, question="q1", standalone_question="q1",
        answer="a1", citations=[],
        verdict="assumption", assumptions=["Assuming X."],
        clarification_question=None, unanswerable_reason=None,
    )
    assert turn.verdict == "assumption"
    assert turn.assumptions == ["Assuming X."]
    assert turn.clarification_question is None
    assert turn.unanswerable_reason is None


def test_append_turn_defaults_verdict_to_answerable(db_session):
    conv = _make_conversation(db_session)
    turn = conversation_turn_service.append_turn(
        db_session, conv.id, question="q1", standalone_question="q1", answer="a1", citations=[],
    )
    assert turn.verdict == "answerable"
    assert turn.assumptions == []
