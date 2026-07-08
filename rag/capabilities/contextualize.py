"""Conversation follow-up contextualization.

Discipline from Phase 5.5:
- rewrite follow-ups into standalone questions first
- let retrieval / answerability / generation operate on the standalone form
- never pass raw chat history directly into retrieval or generation
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_CONTEXT_REWRITE_PROMPT = """\
Rewrite the follow-up question as a self-contained standalone question using the conversation history.
Output ONLY the rewritten question — no explanation, no prefix, no quotes.

Conversation history (most recent last):
{history}

Follow-up question: {question}

Standalone question:"""

_GRADE_RE = re.compile(r"\b(E\s?\d+|KR\s?\d+[a-zA-Z]?)\b", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d+)\s*(?:Jahre|Jahren|years)\b", re.IGNORECASE)
_STAGE_RE = re.compile(r"\bStufe\s*(\d+)\b", re.IGNORECASE)
_FOLLOWUP_PREFIX_RE = re.compile(
    r"^\s*(und|wie\s+sieht\s+es\s+mit|what\s+about|and)\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"\b(verdient|entgelt|gehalt|vergütung|salary|amount)\b", re.IGNORECASE)


def _llm_rewrite(question: str, history: list[dict]) -> str:
    from rag.infra.models.llm import get_llm
    recent = history[-5:]
    lines: list[str] = []
    for t in recent:
        uq = t.get("user_question") or t.get("standalone_question") or ""
        ans = (t.get("answer") or "")[:300]
        if uq:
            lines.append(f"User: {uq}")
        if ans:
            lines.append(f"Assistant: {ans}")
    history_text = "\n".join(lines)
    try:
        llm = get_llm()
        response = llm.invoke(_CONTEXT_REWRITE_PROMPT.format(history=history_text, question=question))
        rewritten = response.content.strip().strip('"\'')
        return rewritten if rewritten else question
    except Exception:
        return question


@dataclass
class ContextualizationResult:
    standalone_question: str
    was_contextualized: bool = False
    is_followup: bool = False


def normalize_question(question: str) -> str:
    text = question.strip().lower()
    text = re.sub(r"[?!.]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_last_grade(turn_history: list[dict[str, Any]]) -> str | None:
    for turn in reversed(turn_history):
        for candidate in (turn.get("standalone_question"), turn.get("user_question")):
            if not candidate:
                continue
            match = _GRADE_RE.search(candidate)
            if match:
                return match.group(1).replace("  ", " ").strip()
    return None


def _last_question(turn_history: list[dict[str, Any]]) -> str | None:
    for turn in reversed(turn_history):
        candidate = turn.get("standalone_question") or turn.get("user_question")
        if candidate:
            return str(candidate)
    return None


def _looks_followup(question: str) -> bool:
    stripped = question.strip()
    return bool(_FOLLOWUP_PREFIX_RE.match(stripped)) or stripped.lower().startswith("und ")


def contextualize_question(question: str, turn_history: list[dict[str, Any]] | None = None) -> ContextualizationResult:
    history = turn_history or []
    stripped = question.strip()
    if not stripped:
        return ContextualizationResult(standalone_question=question)

    has_grade = bool(_GRADE_RE.search(stripped))
    if has_grade or not _looks_followup(stripped):
        return ContextualizationResult(standalone_question=question, was_contextualized=False, is_followup=False)

    last_grade = _extract_last_grade(history)
    if not last_grade:
        if history:
            standalone = _llm_rewrite(stripped, history)
            return ContextualizationResult(
                standalone_question=standalone,
                was_contextualized=standalone != stripped,
                is_followup=True,
            )
        return ContextualizationResult(standalone_question=question, was_contextualized=False, is_followup=True)

    years = _YEARS_RE.search(stripped)
    stage = _STAGE_RE.search(stripped)
    previous = _last_question(history) or ""
    amount_intent = bool(_AMOUNT_RE.search(stripped) or _AMOUNT_RE.search(previous))

    if years:
        years_value = years.group(1)
        if amount_intent:
            standalone = f"Was verdient {last_grade} nach {years_value} Jahren?"
        else:
            standalone = f"Was gilt für {last_grade} nach {years_value} Jahren?"
        return ContextualizationResult(standalone_question=standalone, was_contextualized=True, is_followup=True)

    if stage:
        standalone = f"Was verdient {last_grade} in Stufe {stage.group(1)}?"
        return ContextualizationResult(standalone_question=standalone, was_contextualized=True, is_followup=True)

    standalone = _llm_rewrite(stripped, history)
    return ContextualizationResult(
        standalone_question=standalone,
        was_contextualized=standalone != stripped,
        is_followup=True,
    )