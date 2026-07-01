from rag.capabilities.answerability import (
    AnswerabilityResult,
    check_structural_coherence,
    check_temporal_guard,
    classify,
)
from rag.models import RetrievedChunk


def _chunk(content: str, doc_version: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        content=content,
        score=1.0,
        metadata={"page_numbers": [30], "heading_path": [], "bboxes": [], "doc_version": doc_version},
    )


def test_classify_missing_grade_requests_clarification():
    result = classify("und nach 6 Jahren?", [])
    assert result.verdict == "clarification"
    assert "Entgeltgruppe" in (result.clarification_question or "")


def test_temporal_guard_declines_current_amount_from_2018_table():
    resolver_result = {
        "resolver_unit": "EUR",
        "resolver_steps": [{"result": {"unit": "stufe", "formatted": "Stufe 4"}}],
    }
    guard = check_temporal_guard(
        "Was ist das aktuelle Entgelt nach 6 Jahren?",
        resolver_result,
        [_chunk("Entgeltgruppe E 12 (E12), Stufe 4: 4.609,96 €", doc_version="TV-L 2018")],
    )
    assert guard is not None
    assert guard["stage"] == "Stufe 4"


def test_structural_coherence_catches_amount_mismatch():
    resolver_result = {
        "resolver_unit": "EUR",
        "resolver_formatted": "4.500,00 €",
        "resolver_value": "4500.00",
        "resolver_steps": [{"result": {"unit": "stufe", "formatted": "Stufe 4"}}],
    }
    guard = check_structural_coherence(
        "Was verdient E12 nach 6 Jahren?",
        resolver_result,
        [_chunk("Entgeltgruppe E 12 (E12), Stufe 4: 4.609,96 €")],
    )
    assert guard is not None