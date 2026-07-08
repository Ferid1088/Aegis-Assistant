import pytest
from unittest.mock import MagicMock, patch
from rag.domain.models import RetrievedChunk


def _make_chunk(chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id, content="text", score=score,
        metadata={"page_numbers": [1], "heading_path": [], "bboxes": []},
    )


def test_maybe_hyde_skips_when_disabled():
    """maybe_hyde returns fused unchanged when hyde_enabled=False."""
    from rag.graphs.query import maybe_hyde
    state = {
        "question": "Was ist Urlaubsanspruch?",
        "fused": [_make_chunk("a", 0.1)],
        "lang": "de",
    }
    with patch("rag.graphs.query.settings") as mock_settings:
        mock_settings.hyde_enabled = False
        mock_settings.hyde_threshold = 0.3
        result = maybe_hyde(state)
    assert result == {}  # no state change


def test_maybe_hyde_skips_when_score_above_threshold():
    """maybe_hyde skips when top score exceeds threshold."""
    from rag.graphs.query import maybe_hyde
    state = {
        "question": "Was ist Urlaubsanspruch?",
        "fused": [_make_chunk("a", 0.9), _make_chunk("b", 0.5)],
        "lang": "de",
    }
    with patch("rag.graphs.query.settings") as mock_settings:
        mock_settings.hyde_enabled = True
        mock_settings.hyde_threshold = 0.3
        result = maybe_hyde(state)
    assert result == {}


def test_maybe_hyde_fires_when_score_below_threshold():
    """maybe_hyde fires and extends fused when top score is below threshold."""
    from rag.graphs.query import maybe_hyde
    from rag.capabilities.search.search_service import SearchService

    low_score_chunk = _make_chunk("a", 0.1)
    hyde_chunk = _make_chunk("hyde1", 0.8)

    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = "Ein Urlaubsanspruch beträgt 24 Tage."

    mock_search = MagicMock(spec=SearchService)
    mock_search.search_dense.return_value = [hyde_chunk]

    state = {
        "question": "Was ist Urlaubsanspruch?",
        "fused": [low_score_chunk],
        "lang": "de",
        "doc_filter": None,
        "user_levels": None,
        "intended_types": None,
        "tenant_id": "default",
    }

    with patch("rag.graphs.query.settings") as mock_settings, \
         patch("rag.graphs.query.get_llm", return_value=mock_llm), \
         patch("rag.graphs.query._get_search", return_value=mock_search):
        mock_settings.hyde_enabled = True
        mock_settings.hyde_threshold = 0.3
        mock_settings.acl_enforce = False
        mock_settings.version_filter = False
        mock_settings.rrf_k = 60
        mock_settings.fusion_candidates = 40
        result = maybe_hyde(state)

    assert "fused" in result
    chunk_ids = {c.chunk_id for c in result["fused"]}
    assert "hyde1" in chunk_ids
