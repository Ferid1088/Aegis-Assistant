"""Answerability gate — answer / assume / clarify / decline classification.

This implementation is intentionally conservative: when upstream Phase 5 rule structure
is missing (trigger / required_inputs / validity), it prefers clarify/decline instead of
guessing. That makes the gate safe on today's partial repository state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any

from rag.capabilities.math_engine import parse_decimal
from rag.crosscutting.context import Context
from rag.crosscutting.observability.tracing import set_span_attribute, traced
from rag.models import Computation, ComputationStep, Predicate, RetrievedChunk, RuleArtifact

_GRADE_RE = re.compile(r"\b(E\s?\d+|KR\s?\d+[a-zA-Z]?)\b", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d+)\s*(?:Jahre|Jahren|years)\b", re.IGNORECASE)
_CURRENT_RE = re.compile(r"\b(aktuell\w*|derzeit|heute|current)\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\b(verdient|entgelt|gehalt|vergütung|salary|amount)\b", re.IGNORECASE)
_PROMOTION_RE = re.compile(r"\b(höhergruppiert|hoehergruppiert|promotion|höhergruppierung)\b", re.IGNORECASE)
_NEW_HIRE_RE = re.compile(r"\b(neueinstellung|new hire|neu eingestellt)\b", re.IGNORECASE)

SAFE_DEFAULTS: dict[str, str] = {
    # Reserved seam for future multi-domain defaults. Kept deliberately tiny/safe.
}


@dataclass
class AnswerabilityResult:
    verdict: str
    assumptions: list[str] = field(default_factory=list)
    clarification_question: str | None = None
    unanswerable_reason: str | None = None
    gate_candidate_rules: list[dict[str, Any]] = field(default_factory=list)
    extracted_inputs: dict[str, Any] = field(default_factory=dict)


def _extract_question_inputs(question: str) -> dict[str, Any]:
    grade_match = _GRADE_RE.search(question)
    years_match = _YEARS_RE.search(question)
    if _PROMOTION_RE.search(question):
        trigger = "promotion"
    elif _NEW_HIRE_RE.search(question):
        trigger = "new_hire"
    elif years_match:
        trigger = "step_progression"
    else:
        trigger = None

    return {
        "grade": grade_match.group(1).replace("  ", " ").strip() if grade_match else None,
        "years_continuous": years_match.group(1) if years_match else None,
        "trigger": trigger,
        "asks_current": bool(_CURRENT_RE.search(question)),
        "asks_amount": bool(_AMOUNT_RE.search(question)),
    }


def _parse_predicates(raw: list[dict[str, Any]] | None) -> list[Predicate]:
    predicates: list[Predicate] = []
    for item in raw or []:
        try:
            predicates.append(Predicate(**item))
        except Exception:
            continue
    return predicates


def load_candidate_rules(rules_path: str = "data/progression_rules.json") -> list[RuleArtifact]:
    path = Path(rules_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []

    rules: list[RuleArtifact] = []
    for raw in data:
        comp_data = raw.get("computation")
        computation = None
        if comp_data:
            try:
                computation = Computation(
                    type=comp_data["type"],
                    steps=[ComputationStep(**s) for s in comp_data.get("steps", [])],
                    thresholds=comp_data.get("thresholds", []),
                    tree=comp_data.get("tree", {}),
                    scope=comp_data.get("scope", {}),
                )
            except Exception:
                computation = None
        try:
            rules.append(RuleArtifact(
                rule_id=raw.get("rule_id"),
                rule_kind=raw.get("rule_kind", "default"),
                trigger=raw.get("trigger"),
                quality=raw.get("quality", "uncertain"),
                statement=raw.get("statement", ""),
                conditions=_parse_predicates(raw.get("conditions")),
                condition_logic=raw.get("condition_logic", "all"),
                required_inputs=raw.get("required_inputs", []),
                consequence=raw.get("consequence", "derived_value"),
                variables=raw.get("variables", []),
                scope=_parse_predicates(raw.get("scope")),
                overrides=raw.get("overrides", []),
                depends_on=raw.get("depends_on", []),
                domain=raw.get("domain", "document"),
                source_doc_id=raw.get("source_doc_id", raw.get("chunk_id", "")),
                source_page=raw.get("source_page") or 0,
                source_chunk_id=raw.get("source_chunk_id", raw.get("chunk_id", "")),
                source_quote=(raw.get("source_quote") or raw.get("statement", ""))[:200],
                doc_version=raw.get("doc_version"),
                valid_from=raw.get("valid_from"),
                valid_to=raw.get("valid_to"),
                confidence=float(raw.get("confidence", 0.5)),
                computation=computation,
            ))
        except Exception:
            continue
    return rules


def _summarize_rule(rule: RuleArtifact) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "rule_kind": rule.rule_kind,
        "trigger": rule.trigger,
        "quality": rule.quality,
        "required_inputs": rule.required_inputs,
        "variables": rule.variables,
        "doc_version": rule.doc_version,
        "statement": rule.statement[:120],
    }


def _required_inputs_from_rule(rule: RuleArtifact) -> list[str]:
    if rule.required_inputs:
        return list(rule.required_inputs)
    if rule.conditions:
        return sorted({p.variable for p in rule.conditions if p.variable and p.variable not in SAFE_DEFAULTS})
    return []


def _check_trigger_scope(question_inputs: dict[str, Any], rules: list[RuleArtifact]) -> AnswerabilityResult | None:
    trigger = question_inputs.get("trigger")
    if trigger != "promotion":
        return None

    promotion_rules = [
        r for r in rules
        if r.trigger == "promotion" or "höhergrupp" in r.statement.lower() or "§17" in r.statement.lower()
    ]
    if promotion_rules:
        return None

    return AnswerabilityResult(
        verdict="unanswerable",
        unanswerable_reason="Die Frage beschreibt eine Höhergruppierung/Beförderung, aber dafür wurde keine passende Regel im Korpus gefunden.",
    )


def _check_required_inputs(question_inputs: dict[str, Any], rules: list[RuleArtifact]) -> AnswerabilityResult | None:
    required_inputs: set[str] = set()
    for rule in rules:
        required_inputs.update(_required_inputs_from_rule(rule))

    if question_inputs.get("years_continuous") or question_inputs.get("asks_amount"):
        required_inputs.add("grade")

    missing = [name for name in sorted(required_inputs) if name == "grade" and not question_inputs.get("grade")]
    if not missing:
        return None

    assumptionable = [name for name in missing if name in SAFE_DEFAULTS]
    if assumptionable and len(assumptionable) == len(missing):
        return AnswerabilityResult(
            verdict="assumption",
            assumptions=[f"Annahme: {name} = {SAFE_DEFAULTS[name]}" for name in assumptionable],
        )

    if "grade" in missing:
        return AnswerabilityResult(
            verdict="clarification",
            clarification_question="Für welche Entgeltgruppe oder Tabelle soll ich rechnen?",
        )

    return AnswerabilityResult(
        verdict="clarification",
        clarification_question=f"Welche Angabe fehlt genau: {', '.join(missing)}?",
    )


@traced("answerability.classify")
def classify(
    question: str,
    reranked: list[RetrievedChunk],
    candidate_rules: list[RuleArtifact] | None = None,
    ctx: Context | None = None,
) -> AnswerabilityResult:
    del ctx
    rules = candidate_rules if candidate_rules is not None else load_candidate_rules()
    question_inputs = _extract_question_inputs(question)
    summaries = [_summarize_rule(r) for r in rules[:10]]

    result = _check_trigger_scope(question_inputs, rules)
    if result is None:
        result = _check_required_inputs(question_inputs, rules)

    if result is None:
        if question_inputs.get("years_continuous") and not rules:
            result = AnswerabilityResult(
                verdict="unanswerable",
                unanswerable_reason="Es wurden keine berechenbaren Regeln für diese Ableitung gefunden.",
            )
        elif question_inputs.get("asks_amount") and not reranked:
            result = AnswerabilityResult(
                verdict="unanswerable",
                unanswerable_reason="Ich habe keine passenden Belegstellen oder Tabellen für diese Frage gefunden.",
            )
        else:
            result = AnswerabilityResult(verdict="answerable")

    result.gate_candidate_rules = summaries
    result.extracted_inputs = question_inputs
    set_span_attribute("answerability_verdict", result.verdict)
    set_span_attribute("candidate_rule_count", len(rules))
    return result


def extract_structural_stage(resolver_steps: list[dict[str, Any]] | None) -> str | None:
    stages: list[str] = []
    for step in resolver_steps or []:
        result = step.get("result", {})
        if result.get("unit") == "stufe" and result.get("formatted"):
            stages.append(str(result["formatted"]))
    unique = list(dict.fromkeys(stages))
    if len(unique) == 1:
        return unique[0]
    return None


def check_temporal_guard(
    question: str,
    resolver_result: dict[str, Any],
    reranked: list[RetrievedChunk],
) -> dict[str, Any] | None:
    if not _CURRENT_RE.search(question):
        return None
    if resolver_result.get("resolver_unit") != "EUR":
        return None

    versions = [str(c.metadata.get("doc_version", "")) for c in reranked if c.metadata.get("doc_version")]
    if not versions:
        return None

    if any("2018" in v for v in versions):
        return {
            "reason": "Das gefundene Tabellenmaterial ist versioniert (z. B. 2018) und belegt kein aktuelles Entgelt.",
            "stage": extract_structural_stage(resolver_result.get("resolver_steps")),
        }
    return None


def check_structural_coherence(
    question: str,
    resolver_result: dict[str, Any],
    reranked: list[RetrievedChunk],
) -> dict[str, Any] | None:
    stage_values = {
        str(step.get("result", {}).get("formatted"))
        for step in resolver_result.get("resolver_steps", [])
        if step.get("result", {}).get("unit") == "stufe" and step.get("result", {}).get("formatted")
    }
    if len(stage_values) > 1:
        return {"reason": "Die Berechnung ergibt widersprüchliche Stufenwerte."}

    if resolver_result.get("resolver_unit") != "EUR":
        return None

    grade_match = _GRADE_RE.search(question)
    stage = extract_structural_stage(resolver_result.get("resolver_steps"))
    if not grade_match or not stage:
        return None

    grade = grade_match.group(1).strip()
    grade_compact = grade.replace(" ", "")
    stage_num = re.search(r"\d+", stage)
    if not stage_num:
        return None

    expected_amounts = []
    for chunk in reranked:
        content = chunk.content
        if (grade in content or grade_compact in content) and f"Stufe {stage_num.group()}" in content:
            match = re.search(r"(\d{1,2}\.\d{3},\d{2})\s*€", content)
            if match:
                try:
                    expected_amounts.append(parse_decimal(match.group(1) + " €"))
                except Exception:
                    continue

    if not expected_amounts:
        return None

    try:
        actual = parse_decimal(resolver_result.get("resolver_formatted") or resolver_result.get("resolver_value"))
    except Exception:
        return {"reason": "Das Resolver-Ergebnis enthält keinen sauber vergleichbaren Geldwert."}

    if all(actual != expected for expected in expected_amounts):
        return {"reason": "Der berechnete Geldwert passt nicht zur gefundenen Tabellenzeile für Gruppe/Stufe."}
    return None