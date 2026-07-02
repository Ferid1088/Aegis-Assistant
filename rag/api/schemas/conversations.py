from pydantic import BaseModel


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
