"""Metadata obligation policy — admin-configurable, per-field, per-department (02.1 §4.3).

Deterministic; no LLM. Ingestion validates against this policy before accepting
a document — missing a required field means quarantine, not silent ingestion.
"""

from dataclasses import dataclass, field


@dataclass
class MetadataPolicyRule:
    field: str
    required: bool
    scope: str = "global"  # "global" | "department"
    department_id: str | None = None
    exceptions: tuple[str, ...] = field(default_factory=tuple)  # department_ids excluded from a global rule


def is_field_required(rules: list[MetadataPolicyRule], field: str, department_id: str | None) -> bool:
    """Department-scoped rule wins over global (with-exceptions) over no rule at all."""
    dept_rule = next(
        (r for r in rules if r.field == field and r.scope == "department" and r.department_id == department_id),
        None,
    )
    if dept_rule is not None:
        return dept_rule.required

    global_rule = next((r for r in rules if r.field == field and r.scope == "global"), None)
    if global_rule is None:
        return False
    if department_id is not None and department_id in global_rule.exceptions:
        return False
    return global_rule.required


def validate_metadata(
    values: dict[str, object | None],
    rules: list[MetadataPolicyRule],
    department_id: str | None,
) -> list[str]:
    """Returns missing required fields. Empty list = valid, ready to ingest."""
    fields = {r.field for r in rules}
    missing = []
    for field_name in fields:
        if is_field_required(rules, field_name, department_id) and not values.get(field_name):
            missing.append(field_name)
    return missing
