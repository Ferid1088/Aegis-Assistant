import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, get_current_user, require_permission
from rag.api.schemas.conversations import (
    ConversationResponse, ConversationSummaryResponse, ErasureResponse, LegalHoldRequest,
    MessageRequest, MessageResponse, TransitionRequest, TurnResponse,
)
from rag.config import settings
from rag.crosscutting.security.audit_events import record_admin_change
from rag.crosscutting.security.generation_limits import (
    check_and_increment_inflight_generation, decrement_inflight_generation,
)
from rag.crosscutting.security.rate_limit import limiter
from rag.domain import conversation_service, conversation_turn_service
from rag.domain.conversation import ConversationState
from rag.graphs.query import build_query_graph
from rag.storage.document_store import SQLiteDocumentStore
from rag.storage.sql.base import get_db
from rag.storage.sql.models import Conversation, ConversationTurn

router = APIRouter()

_MAX_HISTORY_TURNS = 8  # mirrors rag/graphs/query.py's own _MAX_TURNS constant


def _to_response(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=str(conv.id), owner_id=str(conv.owner_id), state=conv.state,
        legal_hold=conv.legal_hold, erasure_requested=conv.erasure_requested,
        retention_days=conv.retention_days, encryption_key_id=conv.encryption_key_id,
    )


def _enrich_citations(raw_citations: list[dict]) -> list[dict]:
    store = SQLiteDocumentStore()
    enriched = []
    for c in raw_citations:
        logical_doc_id = c.get("logical_doc_id")
        document_title = "(unknown document)"
        version_no = 0
        if logical_doc_id:
            versions = store.get_versions(logical_doc_id)
            active = next((v for v in versions if v.is_active), None)
            if active:
                document_title = Path(active.filename).stem
                version_no = active.version_no
        page_numbers = c.get("page_numbers") or []
        bboxes = c.get("bboxes") or []
        region = None
        if bboxes and isinstance(bboxes[0], dict) and {"x", "y", "width", "height"} <= bboxes[0].keys():
            b = bboxes[0]
            region = (b["x"], b["y"], b["width"], b["height"])
        enriched.append({
            "chunk_id": c.get("chunk_id"),
            "document_id": logical_doc_id,
            "document_title": document_title,
            "version_no": version_no,
            "page": page_numbers[0] if page_numbers else 0,
            "region": region,
        })
    return enriched


def _summarize(db: Session, conv: Conversation) -> ConversationSummaryResponse:
    first_question = db.execute(
        select(ConversationTurn.question)
        .where(ConversationTurn.conversation_id == conv.id)
        .order_by(ConversationTurn.turn_index.asc())
        .limit(1)
    ).scalar_one_or_none()
    message_count = db.execute(
        select(func.count()).select_from(ConversationTurn)
        .where(ConversationTurn.conversation_id == conv.id)
    ).scalar_one()
    title = first_question[:60] if first_question else "New conversation"
    return ConversationSummaryResponse(
        id=str(conv.id), title=title, updated_at=conv.updated_at.isoformat(),
        message_count=message_count, locked=conv.state != ConversationState.ACTIVE.value,
    )


@router.post("", response_model=ConversationResponse, status_code=201)
def create_conversation(
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conv = conversation_service.create_conversation(db, current.user.id)
    return _to_response(conv)


@router.get("", response_model=list[ConversationSummaryResponse])
def list_conversations(
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationSummaryResponse]:
    convs = conversation_service.list_owned_conversations(db, current.user.id)
    visible = [
        c for c in convs
        if c.state not in (ConversationState.SOFT_DELETED.value, ConversationState.PURGED.value)
    ]
    return [_summarize(db, c) for c in visible]


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: uuid.UUID,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    try:
        conv = conversation_service.get_owned_conversation(db, conversation_id, current.user.id)
    except conversation_service.ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    return _to_response(conv)


@router.post("/{conversation_id}/transition", response_model=ConversationResponse)
def transition(
    conversation_id: uuid.UUID,
    body: TransitionRequest,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    try:
        conv = conversation_service.get_owned_conversation(db, conversation_id, current.user.id)
    except conversation_service.ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc

    try:
        target = ConversationState(body.target_state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid target_state: {body.target_state}") from exc

    try:
        conv = conversation_service.transition_conversation(db, conv, target)
    except conversation_service.TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _to_response(conv)


@router.post("/{conversation_id}/erasure-request", response_model=ErasureResponse)
def erasure_request(
    conversation_id: uuid.UUID,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ErasureResponse:
    try:
        conv = conversation_service.get_owned_conversation(db, conversation_id, current.user.id)
    except conversation_service.ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc

    action, reason = conversation_service.request_erasure(db, conv)
    return ErasureResponse(action=action, reason=reason)


@router.post("/{conversation_id}/legal-hold", response_model=ConversationResponse)
def legal_hold(
    conversation_id: uuid.UUID,
    body: LegalHoldRequest,
    current: AuthenticatedUser = Depends(require_permission("admin:conversations")),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    try:
        conv = conversation_service.get_conversation(db, conversation_id)
    except conversation_service.ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc

    conv = conversation_service.set_legal_hold(db, conv, body.hold)
    record_admin_change(
        str(current.user.id), "conversation_legal_hold_set", f"conversation:{conversation_id}",
        new_value={"legal_hold": body.hold},
    )
    return _to_response(conv)


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
@limiter.limit("10/minute")
def post_message(
    request: Request,
    conversation_id: uuid.UUID,
    body: MessageRequest,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    try:
        conv = conversation_service.get_owned_conversation(db, conversation_id, current.user.id)
    except conversation_service.ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc

    if conv.state != ConversationState.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"conversation is {conv.state}, not active")

    if not check_and_increment_inflight_generation(settings.max_inflight_generations):
        raise HTTPException(status_code=429, detail="too many concurrent generations, try again shortly")

    recent = conversation_turn_service.list_recent_turns(db, conversation_id, limit=_MAX_HISTORY_TURNS)
    state = {
        "question": body.question,
        "turn_history": conversation_turn_service.to_turn_history(recent),
        "user_levels": current.auth_subject.effective_levels,
    }
    if body.doc_filter:
        state["doc_filter"] = body.doc_filter

    try:
        result = build_query_graph().invoke(
            state, config={"configurable": {"thread_id": str(conversation_id)}},
        )
    finally:
        decrement_inflight_generation()

    turn = conversation_turn_service.append_turn(
        db, conversation_id, question=body.question,
        standalone_question=result.get("standalone_question", body.question),
        answer=result.get("answer", ""),
        citations=_enrich_citations(result.get("citations", [])),
        verdict=result.get("answerability_verdict", "answerable"),
        assumptions=result.get("assumptions", []),
        clarification_question=result.get("clarification_question"),
        unanswerable_reason=result.get("unanswerable_reason"),
    )
    return MessageResponse(
        turn_index=turn.turn_index, answer=turn.answer, citations=turn.citations,
        verdict=turn.verdict, assumptions=turn.assumptions,
        clarification_question=turn.clarification_question,
        unanswerable_reason=turn.unanswerable_reason,
    )


@router.get("/{conversation_id}/messages", response_model=list[TurnResponse])
def list_messages(
    conversation_id: uuid.UUID,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TurnResponse]:
    try:
        conversation_service.get_owned_conversation(db, conversation_id, current.user.id)
    except conversation_service.ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc

    turns = conversation_turn_service.list_recent_turns(db, conversation_id, limit=1000)
    return [
        TurnResponse(
            turn_index=t.turn_index, question=t.question, answer=t.answer, citations=t.citations,
            verdict=t.verdict, assumptions=t.assumptions,
            clarification_question=t.clarification_question, unanswerable_reason=t.unanswerable_reason,
        )
        for t in turns
    ]
