from rag.domain.document_lifecycle import (
    DocumentVersion,
    LogicalDocument,
    ProcessingState,
    can_transition_processing,
    next_version_no,
    resolve_identity,
    transition_processing,
)


def test_resolve_identity_filesystem_is_deterministic_and_normalized():
    a = resolve_identity("filesystem", path="/Docs/TV_L.pdf")
    b = resolve_identity("filesystem", path="/docs/TV_L.pdf")
    assert a == b  # case-insensitive normalization
    assert a.startswith("filesystem:")


def test_resolve_identity_filesystem_different_paths_differ():
    a = resolve_identity("filesystem", path="/docs/TV_L.pdf")
    b = resolve_identity("filesystem", path="/docs/other.pdf")
    assert a != b


def test_resolve_identity_connector():
    key = resolve_identity("connector", source_name="sharepoint", record_id="123")
    assert key == "connector:sharepoint:123"


def test_resolve_identity_manual():
    key = resolve_identity("manual", logical_key="contract-x")
    assert key == "manual:contract-x"


def test_resolve_identity_unknown_source_raises():
    try:
        resolve_identity("carrier_pigeon", path="x")
        assert False, "should have raised"
    except ValueError:
        pass


def test_next_version_no_empty():
    assert next_version_no([]) == 1


def test_next_version_no_increments_from_max():
    assert next_version_no([1, 2, 3]) == 4


def test_processing_state_forward_progression_valid():
    assert can_transition_processing(ProcessingState.QUEUED, ProcessingState.CONVERTING)
    assert can_transition_processing(ProcessingState.CONVERTING, ProcessingState.CHUNKING)
    assert can_transition_processing(ProcessingState.CHUNKING, ProcessingState.EMBEDDING)
    assert can_transition_processing(ProcessingState.EMBEDDING, ProcessingState.INDEXING)
    assert can_transition_processing(ProcessingState.INDEXING, ProcessingState.INDEXED)
    assert can_transition_processing(ProcessingState.INDEXED, ProcessingState.ACTIVE)


def test_processing_state_cannot_skip_steps():
    assert not can_transition_processing(ProcessingState.QUEUED, ProcessingState.EMBEDDING)


def test_processing_state_any_step_can_fail_or_quarantine():
    assert can_transition_processing(ProcessingState.CONVERTING, ProcessingState.FAILED)
    assert can_transition_processing(ProcessingState.CHUNKING, ProcessingState.QUARANTINED)


def test_processing_state_failed_can_retry_to_queued():
    assert can_transition_processing(ProcessingState.FAILED, ProcessingState.QUEUED)


def test_processing_state_active_and_quarantined_are_terminal():
    assert not can_transition_processing(ProcessingState.ACTIVE, ProcessingState.QUEUED)
    assert not can_transition_processing(ProcessingState.QUARANTINED, ProcessingState.INDEXED)


def test_transition_processing_mutates_and_reports():
    version = DocumentVersion(
        version_id="v1", logical_doc_id="L1", version_no=1,
        content_hash="h1", filename="f.pdf",
    )
    ok, msg = transition_processing(version, ProcessingState.CONVERTING)
    assert ok and version.processing_state == ProcessingState.CONVERTING
    assert "converting" in msg


def test_transition_processing_rejects_invalid_jump():
    version = DocumentVersion(
        version_id="v1", logical_doc_id="L1", version_no=1,
        content_hash="h1", filename="f.pdf", processing_state=ProcessingState.QUEUED,
    )
    ok, msg = transition_processing(version, ProcessingState.INDEXED)
    assert not ok
    assert version.processing_state == ProcessingState.QUEUED  # unchanged


def test_logical_document_defaults():
    doc = LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf")
    assert doc.tenant_id == "default"
    assert doc.access_level == []
    assert doc.project_id is None
