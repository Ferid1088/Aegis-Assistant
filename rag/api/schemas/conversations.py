from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ConversationResponse(BaseModel):
    id: str
    owner_id: str
    state: str
    legal_hold: bool
    erasure_requested: bool
    retention_days: int | None
    encryption_key_id: str | None


class TransitionRequest(BaseModel):
    target_state: str


class ErasureResponse(BaseModel):
    action: str
    reason: str


class LegalHoldRequest(BaseModel):
    hold: bool


class MessageRequest(BaseModel):
    question: str
    doc_filter: dict | None = None


class CitationResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    chunk_id: str
    document_id: str | None
    document_title: str
    version_no: int
    page: int
    region: tuple[float, float, float, float] | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    turn_index: int
    answer: str
    citations: list[CitationResponse]
    verdict: str
    assumptions: list[str]
    clarification_question: str | None
    unanswerable_reason: str | None


class TurnResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    turn_index: int
    question: str
    answer: str
    citations: list[CitationResponse]
    verdict: str
    assumptions: list[str]
    clarification_question: str | None
    unanswerable_reason: str | None


class ConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str
    updated_at: str
    message_count: int
    locked: bool
