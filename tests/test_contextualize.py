from unittest.mock import patch

from rag.capabilities.contextualize import contextualize_question, normalize_question


def test_followup_after_grade_becomes_standalone_question():
    result = contextualize_question(
        "und nach 6 Jahren?",
        [{"standalone_question": "Was verdient E12?"}],
    )
    assert result.was_contextualized is True
    assert result.is_followup is True
    assert result.standalone_question == "Was verdient E12 nach 6 Jahren?"


def test_followup_without_history_stays_fragment_for_gate_to_clarify():
    # Empty history: nothing to rewrite from — stay fragment, gate handles it
    result = contextualize_question("und nach 6 Jahren?", [])
    assert result.is_followup is True
    assert result.was_contextualized is False
    assert result.standalone_question == "und nach 6 Jahren?"


def test_normalize_question_exact_repeat_identity():
    assert normalize_question(" Was verdient E12? ") == normalize_question("was verdient e12")


def test_semantic_followup_with_history_uses_llm_rewrite():
    """When heuristics can't extract a grade/years/stage, LLM rewrites the semantic follow-up."""
    rewritten = "Does the holiday rule also apply to full-time workers?"
    with patch("rag.capabilities.contextualize._llm_rewrite", return_value=rewritten) as mock_llm:
        result = contextualize_question(
            "and what about full-time workers?",
            [{"standalone_question": "What are the holiday rules?", "answer": "Employees get 30 days."}],
        )
    mock_llm.assert_called_once()
    assert result.is_followup is True
    assert result.was_contextualized is True
    assert result.standalone_question == rewritten


def test_grade_heuristic_skips_llm():
    """Grade+years followup resolves via heuristic — LLM should NOT be called."""
    with patch("rag.capabilities.contextualize._llm_rewrite") as mock_llm:
        result = contextualize_question(
            "und nach 6 Jahren?",
            [{"standalone_question": "Was verdient E12?"}],
        )
    mock_llm.assert_not_called()
    assert result.standalone_question == "Was verdient E12 nach 6 Jahren?"


def test_llm_rewrite_exception_falls_back_to_original():
    """If LLM raises, _llm_rewrite returns the original question unchanged."""
    from rag.capabilities.contextualize import _llm_rewrite
    # get_llm is a local import inside _llm_rewrite; patch it at source
    with patch("rag.infra.models.llm.get_llm", side_effect=RuntimeError("offline")):
        result = _llm_rewrite("und das?", [{"standalone_question": "Was ist X?"}])
    assert result == "und das?"