import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from rag.storage.sql.models import ConversationTurn


def append_turn(
    db: Session, conversation_id: uuid.UUID, *, question: str, standalone_question: str,
    answer: str, citations: list,
) -> ConversationTurn:
    next_index = db.execute(
        select(func.coalesce(func.max(ConversationTurn.turn_index), 0))
        .where(ConversationTurn.conversation_id == conversation_id)
    ).scalar_one() + 1

    turn = ConversationTurn(
        conversation_id=conversation_id, turn_index=next_index, question=question,
        standalone_question=standalone_question, answer=answer, citations=citations,
    )
    db.add(turn)
    db.commit()
    return turn


def list_recent_turns(db: Session, conversation_id: uuid.UUID, limit: int) -> list[ConversationTurn]:
    rows = list(
        db.execute(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.turn_index.desc())
            .limit(limit)
        ).scalars().all()
    )
    return list(reversed(rows))


def delete_all_for_conversation(db: Session, conversation_id: uuid.UUID) -> None:
    db.execute(delete(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id))
    db.commit()


def to_turn_history(turns: list[ConversationTurn]) -> list[dict]:
    # Key names must match rag.graphs.query.finalize_turn's history.append({...}) exactly,
    # since this history is fed back into the graph as `turn_history` state. Note that the
    # question key there is "user_question", not "question".
    return [
        {"user_question": t.question, "standalone_question": t.standalone_question, "answer": t.answer}
        for t in turns
    ]
