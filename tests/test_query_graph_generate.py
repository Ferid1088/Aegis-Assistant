from unittest.mock import MagicMock

from rag.graphs.query import _generate_impl, generate
from rag.domain.models import RetrievedChunk


def _fake_llm(content: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=content)
    return llm


def test_generate_impl_citations_include_logical_doc_id(monkeypatch):
    monkeypatch.setattr("rag.graphs.query.get_llm", lambda: _fake_llm("the answer"))
    chunk = RetrievedChunk(
        chunk_id="c1", content="some content", score=0.9,
        metadata={"page_numbers": [3], "heading_path": ["A"], "bboxes": [], "logical_doc_id": "doc-123"},
    )
    result = _generate_impl("What is X?", [chunk])
    assert result["citations"][0]["logical_doc_id"] == "doc-123"


def test_generate_impl_citation_logical_doc_id_is_none_when_absent(monkeypatch):
    monkeypatch.setattr("rag.graphs.query.get_llm", lambda: _fake_llm("the answer"))
    chunk = RetrievedChunk(
        chunk_id="c1", content="some content", score=0.9,
        metadata={"page_numbers": [3], "heading_path": [], "bboxes": []},
    )
    result = _generate_impl("What is X?", [chunk])
    assert result["citations"][0]["logical_doc_id"] is None


def test_generate_no_longer_bakes_assumptions_into_answer_text(monkeypatch):
    monkeypatch.setattr("rag.graphs.query.get_llm", lambda: _fake_llm("the real answer"))
    chunk = RetrievedChunk(chunk_id="c1", content="content", score=0.9, metadata={"page_numbers": [1]})
    state = {
        "question": "What is X?", "reranked": [chunk], "lang": "de",
        "assumptions": ["Assuming X means the default case."],
    }
    result = generate(state)
    assert result["answer"] == "the real answer"
    assert "Assuming X means the default case." not in result["answer"]


def test_generate_answer_unaffected_when_no_assumptions(monkeypatch):
    monkeypatch.setattr("rag.graphs.query.get_llm", lambda: _fake_llm("plain answer"))
    chunk = RetrievedChunk(chunk_id="c1", content="content", score=0.9, metadata={"page_numbers": [1]})
    state = {"question": "What is X?", "reranked": [chunk], "lang": "de", "assumptions": []}
    result = generate(state)
    assert result["answer"] == "plain answer"
