"""MathEngine capability — deterministic Decimal-based operator evaluation.

The engine evaluates structured computation trees only. It never parses or executes
free-form formulas, and it never performs arithmetic with floats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_UP, ROUND_DOWN
import re
from typing import Any

from rag.crosscutting.context import Context
from rag.crosscutting.observability.tracing import set_span_attribute, traced


ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
}

DEFAULT_ROUNDING = {"mode": "ROUND_HALF_UP", "quantum": "0.01", "label": "kaufmännisch"}
MAX_ABS_VALUE = Decimal("1E18")


@dataclass(frozen=True)
class MathError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluatedValue:
    value: Decimal | str | None
    unit: str | None = None
    formatted: str = ""
    source_quote: str | None = None
    page: int | None = None
    label: str | None = None


@dataclass
class MathResult:
    value: Decimal | str | None
    unit: str | None
    formatted: str
    computation_trace: list[dict] = field(default_factory=list)
    error: MathError | None = None


def parse_decimal(value: Decimal | int | str | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        raise InvalidOperation("empty numeric string")
    text = text.replace("€", "").replace("%", "").strip()
    text = re.sub(r"\s+", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    return Decimal(text)


def format_decimal_german(value: Decimal, unit: str | None = None) -> str:
    if unit == "stufe":
        return f"Stufe {int(value)}"
    if unit in {"percent", "%"}:
        percent = value if unit == "percent" else value
        return f"{_format_german_number(percent)} %"
    if unit == "date":
        return str(value)
    number = _format_german_number(value)
    if unit is None:
        return number
    if unit == "EUR":
        return f"{number} €"
    if unit.startswith("EUR/"):
        suffix = unit.removeprefix("EUR/")
        return f"{number} €/{suffix}"
    if unit == "ratio":
        return number
    return f"{number} {unit}"


def _format_german_number(value: Decimal) -> str:
    if value.as_tuple().exponent >= 0:
        digits = f"{value:.0f}"
        return _group_thousands(digits)

    exponent = value.as_tuple().exponent
    decimals = abs(exponent) if exponent < 0 else 0
    rendered = f"{value:.{decimals}f}"
    integer_part, decimal_part = rendered.split(".", 1)
    return f"{_group_thousands(integer_part)},{decimal_part}"


def _group_thousands(integer_part: str) -> str:
    sign = ""
    digits = integer_part
    if digits.startswith("-"):
        sign = "-"
        digits = digits[1:]
    grouped = []
    while digits:
        grouped.append(digits[-3:])
        digits = digits[:-3]
    return sign + ".".join(reversed(grouped or ["0"]))


def _error(code: str, message: str, trace: list[dict], **details: Any) -> MathResult:
    return MathResult(value=None, unit=None, formatted="", computation_trace=trace,
                      error=MathError(code=code, message=message, details=details))


def _trace_operand(value: EvaluatedValue) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "value": str(value.value) if value.value is not None else None,
        "unit": value.unit,
        "formatted": value.formatted,
    }
    if value.label:
        payload["label"] = value.label
    if value.source_quote:
        payload["source_quote"] = value.source_quote
    if value.page is not None:
        payload["page"] = value.page
    return payload


def _trace_result(value: EvaluatedValue) -> dict[str, Any]:
    return {
        "value": str(value.value) if value.value is not None else None,
        "unit": value.unit,
        "formatted": value.formatted,
    }


def _rounding_policy(override: dict[str, Any] | None = None) -> dict[str, str]:
    policy = dict(DEFAULT_ROUNDING)
    if override:
        policy.update({k: str(v) for k, v in override.items() if v is not None})
    return policy


def _quantize(value: Decimal, policy: dict[str, str]) -> Decimal:
    mode_name = policy.get("mode", DEFAULT_ROUNDING["mode"])
    mode = ROUNDING_MODES.get(mode_name, ROUND_HALF_UP)
    quantum = Decimal(policy.get("quantum", DEFAULT_ROUNDING["quantum"]))
    return value.quantize(quantum, rounding=mode)


def _ensure_numeric(value: EvaluatedValue, trace: list[dict], op: str) -> MathResult | None:
    if not isinstance(value.value, Decimal):
        return _error("incompatible_units", f"{op} requires numeric operands", trace, op=op)
    return None


def _same_units(left: EvaluatedValue, right: EvaluatedValue) -> bool:
    return (left.unit or "") == (right.unit or "")


def _ensure_compatible_units(left: EvaluatedValue, right: EvaluatedValue, trace: list[dict], op: str) -> MathResult | None:
    if not _same_units(left, right):
        return _error(
            "incompatible_units",
            f"{op} requires compatible units: {left.unit} vs {right.unit}",
            trace,
            op=op,
            left_unit=left.unit,
            right_unit=right.unit,
        )
    return None


def _overflow_guard(value: Decimal, trace: list[dict], op: str) -> MathResult | None:
    if abs(value) > MAX_ABS_VALUE:
        return _error("overflow", f"{op} result exceeds max magnitude", trace, op=op, value=str(value))
    return None


def _negative_guard(value: Decimal, trace: list[dict], op: str, node: dict[str, Any]) -> MathResult | None:
    if node.get("non_negative") and value < 0:
        return _error("negative_where_impossible", f"{op} produced a negative value", trace, op=op, value=str(value))
    return None


def _combine_units_for_multiply(left: str | None, right: str | None) -> str | None:
    if left == "ratio":
        return right
    if right == "ratio":
        return left
    if not left:
        return right
    if not right:
        return left
    return f"{left}*{right}"


def _combine_units_for_divide(left: str | None, right: str | None) -> str | None:
    if right == "ratio":
        return left
    if left == right:
        return "ratio"
    if not right:
        return left
    if not left:
        return None
    return f"{left}/{right}"


def _evaluate_leaf(node: dict[str, Any]) -> EvaluatedValue:
    unit = node.get("unit")
    raw_value = node.get("value")
    if unit == "date":
        text = str(raw_value)
        return EvaluatedValue(
            value=text,
            unit=unit,
            formatted=node.get("formatted") or text,
            source_quote=node.get("source_quote"),
            page=node.get("page"),
            label=node.get("label"),
        )
    decimal_value = parse_decimal(raw_value)
    formatted = node.get("formatted") or format_decimal_german(decimal_value, unit)
    return EvaluatedValue(
        value=decimal_value,
        unit=unit,
        formatted=formatted,
        source_quote=node.get("source_quote"),
        page=node.get("page"),
        label=node.get("label"),
    )


def _apply_op(op: str, operands: list[EvaluatedValue], node: dict[str, Any], trace: list[dict], policy: dict[str, str]) -> MathResult | EvaluatedValue:
    numeric_error = next((err for operand in operands if (err := _ensure_numeric(operand, trace, op))), None)
    if numeric_error:
        return numeric_error

    left = operands[0]
    right = operands[1] if len(operands) > 1 else None
    assert isinstance(left.value, Decimal)

    if op == "add":
        assert right is not None and isinstance(right.value, Decimal)
        unit_error = _ensure_compatible_units(left, right, trace, op)
        if unit_error:
            return unit_error
        value = left.value + right.value
        unit = left.unit
    elif op == "subtract":
        assert right is not None and isinstance(right.value, Decimal)
        unit_error = _ensure_compatible_units(left, right, trace, op)
        if unit_error:
            return unit_error
        value = left.value - right.value
        unit = left.unit
    elif op == "multiply":
        assert right is not None and isinstance(right.value, Decimal)
        value = left.value * right.value
        unit = _combine_units_for_multiply(left.unit, right.unit)
    elif op == "divide":
        assert right is not None and isinstance(right.value, Decimal)
        if right.value == 0:
            return _error("division_by_zero", "division by zero", trace, op=op)
        value = left.value / right.value
        unit = _combine_units_for_divide(left.unit, right.unit)
    elif op == "percentage":
        assert right is not None and isinstance(right.value, Decimal)
        rate = left.value
        if left.unit in {"percent", "%"}:
            rate = left.value / Decimal("100")
        elif left.unit not in {"ratio", None}:
            return _error("incompatible_units", "percentage expects ratio or percent as first operand", trace, op=op)
        value = rate * right.value
        unit = right.unit
    elif op == "min":
        assert right is not None and isinstance(right.value, Decimal)
        unit_error = _ensure_compatible_units(left, right, trace, op)
        if unit_error:
            return unit_error
        value = min(left.value, right.value)
        unit = left.unit
    elif op == "max":
        assert right is not None and isinstance(right.value, Decimal)
        unit_error = _ensure_compatible_units(left, right, trace, op)
        if unit_error:
            return unit_error
        value = max(left.value, right.value)
        unit = left.unit
    elif op == "cap":
        assert right is not None and isinstance(right.value, Decimal)
        unit_error = _ensure_compatible_units(left, right, trace, op)
        if unit_error:
            return unit_error
        value = min(left.value, right.value)
        unit = left.unit
    elif op == "floor":
        assert right is not None and isinstance(right.value, Decimal)
        unit_error = _ensure_compatible_units(left, right, trace, op)
        if unit_error:
            return unit_error
        value = max(left.value, right.value)
        unit = left.unit
    elif op == "round":
        round_policy = _rounding_policy(node.get("rounding") or policy)
        value = _quantize(left.value, round_policy)
        unit = left.unit
    else:
        return _error("incompatible_units", f"unknown operator: {op}", trace, op=op)

    overflow = _overflow_guard(value, trace, op)
    if overflow:
        return overflow
    negative = _negative_guard(value, trace, op, node)
    if negative:
        return negative

    result = EvaluatedValue(value=value, unit=unit, formatted=format_decimal_german(value, unit))
    trace.append({"op": op, "operands": [_trace_operand(o) for o in operands], "result": _trace_result(result)})
    return result


def _parse_stufe_label(label: str) -> Decimal:
    match = re.search(r"(\d+)", label)
    if not match:
        raise InvalidOperation(f"cannot parse stage from {label!r}")
    return Decimal(match.group(1))


def _evaluate_cumulative_steps(node: dict[str, Any], trace: list[dict], policy: dict[str, str]) -> MathResult | EvaluatedValue:
    target_result = _evaluate_node(node["target"], trace, policy)
    if isinstance(target_result, MathResult):
        return target_result
    numeric_error = _ensure_numeric(target_result, trace, "cumulative_steps")
    if numeric_error:
        return numeric_error
    assert isinstance(target_result.value, Decimal)

    cumulative = EvaluatedValue(value=Decimal("0"), unit=node.get("target_unit") or target_result.unit or "years", formatted="0")
    current_state = parse_decimal(node.get("start_state", "1"))

    for step in node.get("steps", []):
        increment_leaf = {
            "kind": "lookup",
            "value": step["increment"],
            "unit": step.get("unit", cumulative.unit),
            "source_quote": step.get("source_quote"),
            "page": step.get("page"),
            "label": f"{step.get('from_state', '')} → {step.get('to_state', '')}",
        }
        increment = _evaluate_leaf(increment_leaf)
        added = _apply_op("add", [cumulative, increment], {}, trace, policy)
        if isinstance(added, MathResult):
            return added
        cumulative = added
        current_state = _parse_stufe_label(step.get("to_state", str(current_state)))
        if cumulative.value >= target_result.value:
            result = EvaluatedValue(value=current_state, unit="stufe", formatted=format_decimal_german(current_state, "stufe"))
            trace.append({
                "op": "cumulative_steps",
                "operands": [_trace_operand(target_result), _trace_operand(cumulative)],
                "result": _trace_result(result),
            })
            return result

    return _error(
        "overflow",
        "target exceeds cumulative steps available",
        trace,
        target=str(target_result.value),
        max_cumulative=str(cumulative.value),
    )


def _evaluate_threshold_lookup(node: dict[str, Any], trace: list[dict], policy: dict[str, str]) -> MathResult | EvaluatedValue:
    input_result = _evaluate_node(node["input"], trace, policy)
    if isinstance(input_result, MathResult):
        return input_result
    numeric_error = _ensure_numeric(input_result, trace, "threshold_lookup")
    if numeric_error:
        return numeric_error
    assert isinstance(input_result.value, Decimal)

    thresholds = sorted(node.get("thresholds", []), key=lambda band: parse_decimal(band.get("lower", 0)))
    for band in thresholds:
        lower = parse_decimal(band.get("lower", 0))
        upper_raw = band.get("upper")
        upper = parse_decimal(upper_raw) if upper_raw not in (None, "") else None
        if input_result.value >= lower and (upper is None or input_result.value < upper):
            result_payload = band.get("result", {})
            if isinstance(result_payload, dict):
                if "kind" not in result_payload:
                    result_payload = {"kind": "constant", **result_payload}
                result = _evaluate_leaf(result_payload)
            else:
                result = _evaluate_leaf({"kind": "constant", "value": result_payload, "unit": band.get("result_unit")})
            trace.append({
                "op": "threshold_lookup",
                "operands": [_trace_operand(input_result)],
                "result": _trace_result(result),
            })
            return result

    return _error("overflow", "no matching threshold band", trace, value=str(input_result.value))


def _evaluate_date_offset(node: dict[str, Any], trace: list[dict], policy: dict[str, str]) -> MathResult | EvaluatedValue:
    base_date = str(node.get("base_date", ""))
    offset_result = _evaluate_node(node["offset"], trace, policy)
    if isinstance(offset_result, MathResult):
        return offset_result
    numeric_error = _ensure_numeric(offset_result, trace, "date_offset")
    if numeric_error:
        return numeric_error
    assert isinstance(offset_result.value, Decimal)

    try:
        base = datetime.strptime(base_date, "%Y-%m-%d")
    except ValueError:
        return _error("incompatible_units", f"invalid base date: {base_date}", trace, base_date=base_date)

    offset_unit = node.get("offset_unit", "days")
    offset_int = int(offset_result.value)
    if offset_unit == "days":
        shifted = base + timedelta(days=offset_int)
    elif offset_unit == "months":
        shifted = base + timedelta(days=offset_int * 30)
    elif offset_unit == "years":
        shifted = base + timedelta(days=offset_int * 365)
    else:
        return _error("incompatible_units", f"unknown offset unit: {offset_unit}", trace, offset_unit=offset_unit)

    result = EvaluatedValue(value=shifted.strftime("%Y-%m-%d"), unit="date", formatted=shifted.strftime("%Y-%m-%d"))
    trace.append({
        "op": "date_offset",
        "operands": [_trace_operand(EvaluatedValue(value=base_date, unit="date", formatted=base_date)), _trace_operand(offset_result)],
        "result": _trace_result(result),
    })
    return result


def _evaluate_node(node: dict[str, Any], trace: list[dict], policy: dict[str, str]) -> MathResult | EvaluatedValue:
    kind = node.get("kind")
    if kind in {"constant", "lookup"}:
        try:
            return _evaluate_leaf(node)
        except InvalidOperation as exc:
            return _error("incompatible_units", f"invalid numeric input: {exc}", trace, node=node)

    op = node.get("op")
    if op == "cumulative_steps":
        return _evaluate_cumulative_steps(node, trace, policy)
    if op == "threshold_lookup":
        return _evaluate_threshold_lookup(node, trace, policy)
    if op == "date_offset":
        return _evaluate_date_offset(node, trace, policy)

    operands = []
    for operand_node in node.get("operands", []):
        operand = _evaluate_node(operand_node, trace, policy)
        if isinstance(operand, MathResult):
            return operand
        operands.append(operand)

    return _apply_op(op, operands, node, trace, policy)


class MathEngine:
    """Pure computation capability for structured operator trees."""

    @traced("math.evaluate")
    def evaluate(self, tree: dict[str, Any], ctx: Context | None = None) -> MathResult:
        trace: list[dict] = []
        policy = _rounding_policy(tree.get("rounding"))
        result = _evaluate_node(tree, trace, policy)
        if isinstance(result, MathResult):
            set_span_attribute("op_count", len(trace))
            set_span_attribute("had_error", True)
            return result

        set_span_attribute("op_count", len(trace))
        set_span_attribute("had_error", False)
        return MathResult(
            value=result.value,
            unit=result.unit,
            formatted=result.formatted,
            computation_trace=trace,
            error=None,
        )


def evaluate(tree: dict[str, Any], ctx: Context | None = None) -> MathResult:
    return MathEngine().evaluate(tree, ctx=ctx)
