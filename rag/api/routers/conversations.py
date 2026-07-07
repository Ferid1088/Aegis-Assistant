import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, get_current_user, require_permission
from rag.api.schemas.conversations import (
    ConversationResponse, ErasureResponse, LegalHoldRequest, MessageRequest, MessageResponse,
    TransitionRequest, TurnResponse,
)
from rag.crosscutting.security.audit_events import record_admin_change
from rag.crosscutting.security.rate_limit import limiter
from rag.domain import conversation_service, conversation_turn_service
from rag.domain.conversation import ConversationState
from rag.graphs.query import build_query_graph
from rag.storage.sql.base import get_db
from rag.storage.sql.models import Conversation

router = APIRouter()

_MAX_HISTORY_TURNS = 8  # mirrors rag/graphs/query.py's own _MAX_TURNS constant


def _to_response(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=str(conv.id), owner_id=str(conv.owner_id), state=conv.state,
        legal_hold=conv.legal_hold, erasure_requested=conv.erasure_requested,
        retention_days=conv.retention_days, encryption_key_id=conv.encryption_key_id,
    )


@router.post("", response_model=ConversationResponse, status_code=201)
def create_conversation(
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conv = conversation_service.create_conversation(db, current.user.id)
    return _to_response(conv)


@router.get("", response_model=list[ConversationResponse])
def list_conversations(
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationResponse]:
    convs = conversation_service.list_owned_conversations(db, current.user.id)
    return [_to_response(c) for c in convs]


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

    recent = conversation_turn_service.list_recent_turns(db, conversation_id, limit=_MAX_HISTORY_TURNS)
    state = {
        "question": body.question,
        "turn_history": conversation_turn_service.to_turn_history(recent),
        "user_levels": current.auth_subject.effective_levels,
    }
    if body.doc_filter:
        state["doc_filter"] = body.doc_filter

    result = build_query_graph().invoke(
        state, config={"configurable": {"thread_id": str(conversation_id)}},
    )

    turn = conversation_turn_service.append_turn(
        db, conversation_id, question=body.question,
        standalone_question=result.get("standalone_question", body.question),
        answer=result.get("answer", ""), citations=result.get("citations", []),
    )
    return MessageResponse(turn_index=turn.turn_index, answer=turn.answer, citations=turn.citations)


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
        TurnResponse(turn_index=t.turn_index, question=t.question, answer=t.answer, citations=t.citations)
        for t in turns
    ]
