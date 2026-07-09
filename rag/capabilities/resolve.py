"""Derived-Answer Resolver — deterministic computation over structured extracted rules.

Architecture = C (deterministic spine) + B (LLM fallback, flagged).
Never Approach A (pre-compute derived facts during extraction).

Degradation ladder:
  deterministic resolver (certain) → LLM plan→solve (flagged) → "nicht ableitbar"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from rag.capabilities.math_engine import MathEngine, MathError, parse_decimal
from rag.crosscutting.context import Context
from rag.crosscutting.observability.tracing import traced
from rag.domain.models import Computation, RuleArtifact


@dataclass
class ResolverResult:
    resolved: bool
    value: Decimal | str | None = None
    unit: str | None = None
    formatted: str | None = None
    computation_trace: list[dict] = field(default_factory=list)
    intermediate_steps: list[dict] = field(default_factory=list)
    cited_rules: list[dict] = field(default_factory=list)
    source_rules: list[dict] = field(default_factory=list)
    confidence: str = "deterministic"
    decline_reason: str | None = None
    math_error: MathError | None = None
    answerability_action: str | None = None


def _source_leaf(value: Any, unit: str | None = None, *, label: str | None = None,
                 source_quote: str | None = None, page: int | None = None,
                 kind: str = "constant") -> dict[str, Any]:
    node: dict[str, Any] = {"kind": kind, "value": value, "unit": unit}
    if label:
        node["label"] = label
    if source_quote:
        node["source_quote"] = source_quote
    if page is not None:
        node["page"] = page
    return node


def _question_input_leaf(name: str, value: Any, unit: str | None = None) -> dict[str, Any]:
    return _source_leaf(
        value,
        unit,
        label=name,
        source_quote=f"Frage/Parameter: {name}",
        page=None,
        kind="lookup",
    )


def _math_failure(error: MathError, trace: list[dict]) -> ResolverResult:
    citations = _citations_from_trace(trace)
    return ResolverResult(
        resolved=False,
        decline_reason=f"math_engine:{error.code}",
        computation_trace=trace,
        intermediate_steps=trace,
        cited_rules=citations,
        source_rules=list(citations),
        math_error=error,
        answerability_action="gate",
    )


def _citations_from_trace(trace: list[dict]) -> list[dict]:
    citations: list[dict] = []
    seen: set[tuple[str, int | None]] = set()
    for step in trace:
        for operand in step.get("operands", []):
            source_quote = operand.get("source_quote")
            page = operand.get("page")
            if not source_quote:
                continue
            key = (source_quote, page)
            if key in seen:
                continue
            citations.append({
                "source_quote": source_quote,
                "page": page,
                "label": operand.get("label"),
            })
            seen.add(key)
    return citations


def _rule_source(rule: RuleArtifact) -> dict[str, Any]:
    return {
        "rule_kind": rule.rule_kind,
        "statement": rule.statement,
        "source_quote": rule.source_quote,
        "page": rule.source_page,
        "source_doc_id": rule.source_doc_id,
        "source_chunk_id": rule.source_chunk_id,
    }


def _resolve_value_payload(value: Decimal | str | None, unit: str | None, formatted: str | None) -> Decimal | str | None:
    if unit == "stufe" and formatted:
        return formatted
    return value if value is not None else formatted


def _build_cumulative_steps_tree(comp: Computation, target_value: Decimal) -> dict[str, Any]:
    return {
        "op": "cumulative_steps",
        "target": _question_input_leaf("years_continuous", target_value, unit="years"),
        "target_unit": "years",
        "start_state": "1",
        "steps": [
            {
                "from_state": step.from_state,
                "to_state": step.to_state,
                "increment": step.increment,
                "unit": step.unit,
                "source_quote": step.source_quote,
                "page": step.page,
            }
            for step in comp.steps
        ],
    }


def _build_threshold_lookup_tree(comp: Computation, target_value: Decimal) -> dict[str, Any]:
    return {
        "op": "threshold_lookup",
        "input": _question_input_leaf("target_value", target_value),
        "thresholds": comp.thresholds,
    }


def _build_date_offset_tree(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": "date_offset",
        "base_date": inputs.get("base_date", ""),
        "offset": _question_input_leaf("offset", inputs.get("offset", 0), unit=inputs.get("unit", "days")),
        "offset_unit": inputs.get("unit", "days"),
    }


def _extract_operand(inputs: dict[str, Any], key: str, fallback_unit: str | None = None) -> dict[str, Any]:
    raw = inputs.get(key)
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("kind", "lookup")
        return payload
    return _question_input_leaf(key, raw, unit=fallback_unit)


def _build_tree(comp: Computation, target_value: Decimal | None, inputs: dict[str, Any] | None) -> dict[str, Any] | None:
    if comp.type == "cumulative_steps" and target_value is not None:
        return _build_cumulative_steps_tree(comp, target_value)
    if comp.type == "threshold_lookup" and target_value is not None:
        return _build_threshold_lookup_tree(comp, target_value)
    if comp.type == "date_offset" and inputs:
        return _build_date_offset_tree(inputs)
    if comp.type == "difference" and inputs:
        return {
            "op": "subtract",
            "operands": [
                _extract_operand(inputs, "left"),
                _extract_operand(inputs, "right"),
            ],
        }
    if comp.type == "percentage_of" and inputs:
        return {
            "op": "percentage",
            "operands": [
                _extract_operand(inputs, "percentage", fallback_unit="percent"),
                _extract_operand(inputs, "base"),
            ],
        }
    if comp.type == "proration" and inputs:
        return {
            "op": "multiply",
            "operands": [
                _extract_operand(inputs, "base"),
                _extract_operand(inputs, "ratio", fallback_unit="ratio"),
            ],
        }
    if comp.tree:
        return comp.tree
    return None


@traced("resolve.deterministic")
def resolve(
    rules: list[RuleArtifact],
    target_variable: str,
    target_value: Decimal | int | str | None = None,
    inputs: dict | None = None,
    ctx: Context | None = None,
) -> ResolverResult:
    """Select applicable rules, build a computation tree, and execute via MathEngine."""
    del target_variable

    computable = [r for r in rules if r.computation is not None]
    if not computable:
        return ResolverResult(resolved=False, decline_reason="no computable rules found")

    parsed_target: Decimal | None = None
    if target_value is not None:
        try:
            parsed_target = parse_decimal(target_value)
        except (InvalidOperation, ValueError):
            return ResolverResult(resolved=False, decline_reason=f"invalid target_value: {target_value}")

    engine = MathEngine()
    last_failure: ResolverResult | None = None

    for rule in computable:
        comp = rule.computation
        assert comp is not None
        tree = _build_tree(comp, parsed_target, inputs)
        if not tree:
            continue

        math_result = engine.evaluate(tree, ctx=ctx)
        if math_result.error:
            last_failure = _math_failure(math_result.error, math_result.computation_trace)
            rule_source = _rule_source(rule)
            last_failure.cited_rules.append(rule_source)
            last_failure.source_rules.append(rule_source)
            continue

        citations = _citations_from_trace(math_result.computation_trace)
        rule_source = _rule_source(rule)
        return ResolverResult(
            resolved=True,
            value=_resolve_value_payload(math_result.value, math_result.unit, math_result.formatted),
            unit=math_result.unit,
            formatted=math_result.formatted,
            computation_trace=math_result.computation_trace,
            intermediate_steps=math_result.computation_trace,
            cited_rules=[*citations, rule_source],
            source_rules=[rule_source],
            confidence="deterministic",
        )

    return last_failure or ResolverResult(resolved=False, decline_reason="no matching computation primitive")


@traced("resolve.chain")
def resolve_chain(
    question: str,
    rules: list[RuleArtifact],
    table_lookup_fn=None,
    ctx: Context | None = None,
) -> ResolverResult:
    """Two-step resolution: derive intermediate (e.g. Stufe) then look up final value.

    For "E12 nach 6 Jahren":
      Step 1: cumulative_steps(6 years) → Stufe 4
      Step 2: table_lookup(E12, Stufe 4) → 4.609,96 €
    """
    years_match = re.search(r"(\d+)\s*(?:Jahre|Jahren|years)", question, re.IGNORECASE)
    grade_match = re.search(r"(E\s?\d+|KR\s?\d+\w?)", question, re.IGNORECASE)

    if not years_match or not grade_match:
        return ResolverResult(resolved=False, decline_reason="cannot parse years/grade from question")

    years = parse_decimal(years_match.group(1))
    grade = grade_match.group(1).strip()

    step1 = resolve(rules, target_variable="stufe", target_value=years, ctx=ctx)
    if not step1.resolved:
        return ResolverResult(
            resolved=False,
            decline_reason=f"step 1 failed: {step1.decline_reason}",
            computation_trace=step1.computation_trace,
            intermediate_steps=step1.intermediate_steps,
            cited_rules=step1.cited_rules,
            source_rules=step1.source_rules,
            math_error=step1.math_error,
            answerability_action=step1.answerability_action,
        )

    stufe = step1.formatted or str(step1.value)
    all_cited = list(step1.cited_rules)
    all_sources = list(step1.source_rules)
    all_trace = list(step1.computation_trace)
    all_trace.append({
        "op": "derived",
        "operands": [{"value": str(years), "unit": "years", "formatted": f"{years} Jahre"}],
        "result": {"value": stufe, "unit": "stufe", "formatted": stufe},
    })

    if table_lookup_fn:
        amount = table_lookup_fn(grade, stufe)
        if amount:
            table_trace = {
                "op": "table_lookup",
                "operands": [{"value": grade, "formatted": grade}, {"value": stufe, "unit": "stufe", "formatted": stufe}],
                "result": {"value": amount, "unit": "EUR", "formatted": amount},
            }
            all_trace.append(table_trace)
            all_cited.append({"table_lookup": f"{grade} {stufe}", "amount": amount})
            return ResolverResult(
                resolved=True,
                value=parse_decimal(amount),
                unit="EUR",
                formatted=amount,
                computation_trace=all_trace,
                intermediate_steps=all_trace,
                cited_rules=all_cited,
                source_rules=all_sources,
                confidence="deterministic",
            )

    return ResolverResult(
        resolved=True,
        value=stufe,
        unit="stufe",
        formatted=stufe,
        computation_trace=all_trace,
        intermediate_steps=all_trace,
        cited_rules=all_cited,
        source_rules=all_sources,
        confidence="deterministic (Stufe only, no table lookup)",
    )
