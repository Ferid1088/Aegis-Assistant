"""Tests for lifecycle_gate node and L1 cache TTL in the query graph."""

import time
from unittest.mock import patch

from rag.pipelines.retrieval.nodes import lifecycle_gate, lifecycle_denied


# ── Lifecycle gate ────────────────────────────────────────────────────────

def test_active_conversation_is_allowed():
    state = {"question": "Was ist X?", "conversation_state": "active"}
    result = lifecycle_gate(state)
    assert result["lifecycle_blocked"] is False


def test_soft_deleted_conversation_is_blocked():
    state = {"question": "Was ist X?", "conversation_state": "soft_deleted"}
    result = lifecycle_gate(state)
    assert result["lifecycle_blocked"] is True


def test_purged_conversation_is_blocked():
    state = {"question": "Was ist X?", "conversation_state": "purged"}
    result = lifecycle_gate(state)
    assert result["lifecycle_blocked"] is True


def test_locked_conversation_allows_search():
    # locked blocks modify/delete/rename/append — but NOT search
    state = {"question": "Was ist X?", "conversation_state": "locked"}
    result = lifecycle_gate(state)
    assert result["lifecycle_blocked"] is False


def test_missing_conversation_state_defaults_to_active():
    state = {"question": "Was ist X?"}
    result = lifecycle_gate(state)
    assert result["lifecycle_blocked"] is False


def test_lifecycle_denied_returns_german_message_for_soft_deleted():
    state = {"conversation_state": "soft_deleted"}
    result = lifecycle_denied(state)
    assert result["answer"]
    assert result["citations"] == []
    assert result["response_source"] == "lifecycle_blocked"
    assert "gelöscht" in result["answer"]


def test_lifecycle_denied_returns_message_for_purged():
    state = {"conversation_state": "purged"}
    result = lifecycle_denied(state)
    assert "endgültig" in result["answer"]


# ── L1 cache TTL ─────────────────────────────────────────────────────────

def _make_repeat_cache(normalized_q: str, ts_offset: float = 0.0) -> dict:
    """Helper: build a repeat_cache with a single entry stamped ts_offset seconds ago."""
    return {
        normalized_q: {
            "answer": "cached answer",
            "citations": [],
            "context": "ctx",
            "ts": time.time() - ts_offset,
        }
    }


def test_l1_cache_fresh_entry_is_used(monkeypatch):
    """A cache entry written just now should be a cache hit."""
    from rag.pipelines.retrieval.nodes import contextualize

    normalized_q = "was verdient e12"
    cache = _make_repeat_cache(normalized_q, ts_offset=0)

    # The contextualize node also calls contextualize_question and read_cache;
    # mock them to isolate the TTL logic.
    from rag.capabilities.contextualize import ContextualizationResult
    monkeypatch.setattr(
        "rag.pipelines.retrieval.nodes.contextualize_question",
        lambda q, h: ContextualizationResult(standalone_question="Was verdient E12?"),
    )
    monkeypatch.setattr(
        "rag.pipelines.retrieval.nodes.normalize_question",
        lambda q: normalized_q,
    )
    monkeypatch.setattr("rag.capabilities.cache.read_cache", lambda *a, **kw: None)

    state = {"question": "Was verdient E12?", "repeat_cache": cache, "turn_history": []}
    result = contextualize(state)
    assert result["cache_hit"] is True


def test_l1_cache_expired_entry_is_skipped(monkeypatch):
    """A cache entry older than cache_ttl_answer must be treated as a miss."""
    from rag.pipelines.retrieval.nodes import contextualize
    from rag.config import settings

    normalized_q = "was verdient e12"
    # Stamp it 2× the TTL in the past so it is definitely stale
    cache = _make_repeat_cache(normalized_q, ts_offset=settings.cache_ttl_answer * 2)

    from rag.capabilities.contextualize import ContextualizationResult
    monkeypatch.setattr(
        "rag.pipelines.retrieval.nodes.contextualize_question",
        lambda q, h: ContextualizationResult(standalone_question="Was verdient E12?"),
    )
    monkeypatch.setattr(
        "rag.pipelines.retrieval.nodes.normalize_question",
        lambda q: normalized_q,
    )
    monkeypatch.setattr("rag.capabilities.cache.read_cache", lambda *a, **kw: None)

    state = {"question": "Was verdient E12?", "repeat_cache": cache, "turn_history": []}
    result = contextualize(state)
    assert result["cache_hit"] is False
