"""Logical document vs. document version — the identity/versioning spine (02.1 §1-§3).

A LogicalDocument is the stable *thing* (owns metadata, lifecycle).
A DocumentVersion is one ingested file under it (content_hash, processing state).
Metadata lives on the LOGICAL document; versions are instances (02.1 §1).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LogicalDocumentState(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


class ProcessingState(str, Enum):
    QUEUED = "queued"
    CONVERTING = "converting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ACTIVE = "active"
    FAILED = "failed"
    QUARANTINED = "quarantined"


_FORWARD_PATH: list[ProcessingState] = [
    ProcessingState.QUEUED,
    ProcessingState.CONVERTING,
    ProcessingState.CHUNKING,
    ProcessingState.EMBEDDING,
    ProcessingState.INDEXING,
    ProcessingState.INDEXED,
    ProcessingState.ACTIVE,
]

VALID_PROCESSING_TRANSITIONS: dict[ProcessingState, set[ProcessingState]] = {}
for _i, _state in enumerate(_FORWARD_PATH[:-1]):
    VALID_PROCESSING_TRANSITIONS[_state] = {
        _FORWARD_PATH[_i + 1], ProcessingState.FAILED, ProcessingState.QUARANTINED,
    }
VALID_PROCESSING_TRANSITIONS[ProcessingState.ACTIVE] = set()
VALID_PROCESSING_TRANSITIONS[ProcessingState.FAILED] = {ProcessingState.QUEUED}  # retry with backoff
VALID_PROCESSING_TRANSITIONS[ProcessingState.QUARANTINED] = set()  # needs admin attention, not a code transition


def can_transition_processing(current: ProcessingState, target: ProcessingState) -> bool:
    return target in VALID_PROCESSING_TRANSITIONS.get(current, set())


@dataclass
class DocumentVersion:
    version_id: str
    logical_doc_id: str
    version_no: int
    content_hash: str
    filename: str
    num_pages: int = 0
    is_active: bool = True
    processing_state: ProcessingState = ProcessingState.QUEUED
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


def transition_processing(version: DocumentVersion, target: ProcessingState) -> tuple[bool, str]:
    if not can_transition_processing(version.processing_state, target):
        return False, f"invalid transition: {version.processing_state.value} → {target.value}"
    version.processing_state = target
    return True, f"transitioned to {target.value}"


@dataclass
class LogicalDocument:
    logical_doc_id: str
    source_identity: str
    tenant_id: str = "default"
    department: str | None = None
    access_level: list[str] = field(default_factory=list)
    document_type: str | None = None
    project_id: str | None = None
    phase_id: str | None = None
    state: LogicalDocumentState = LogicalDocumentState.ACTIVE
    created_at: datetime = field(default_factory=_now)


def resolve_identity(source_type: str, **kwargs: str) -> str:
    """Deterministic identity key per source type (02.1 §2.1). NOT content hash —
    a hash *change* is what defines a new version; this key is what ties versions
    into one lineage."""
    if source_type == "filesystem":
        normalized = kwargs["path"].strip().replace("\\", "/").lower()
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        return f"filesystem:{normalized}"
    if source_type == "connector":
        return f"connector:{kwargs['source_name']}:{kwargs['record_id']}"
    if source_type == "manual":
        return f"manual:{kwargs['logical_key']}"
    raise ValueError(f"unknown source_type: {source_type}")


def next_version_no(existing_version_numbers: list[int]) -> int:
    return (max(existing_version_numbers) + 1) if existing_version_numbers else 1
