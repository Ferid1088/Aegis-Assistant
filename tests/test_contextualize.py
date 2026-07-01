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
    result = contextualize_question("und nach 6 Jahren?", [])
    assert result.is_followup is True
    assert result.was_contextualized is False
    assert result.standalone_question == "und nach 6 Jahren?"


def test_normalize_question_exact_repeat_identity():
    assert normalize_question(" Was verdient E12? ") == normalize_question("was verdient e12")