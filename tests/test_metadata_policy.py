from rag.domain.metadata_policy import MetadataPolicyRule, is_field_required, validate_metadata


def test_global_required_applies_everywhere():
    rules = [MetadataPolicyRule(field="department", required=True, scope="global")]
    assert is_field_required(rules, "department", department_id=None)
    assert is_field_required(rules, "department", department_id="hr")


def test_global_optional_field():
    rules = [MetadataPolicyRule(field="project_id", required=False, scope="global")]
    assert not is_field_required(rules, "project_id", department_id="hr")


def test_unknown_field_defaults_to_not_required():
    rules = [MetadataPolicyRule(field="department", required=True, scope="global")]
    assert not is_field_required(rules, "document_type", department_id="hr")


def test_department_scoped_rule_overrides_global():
    rules = [
        MetadataPolicyRule(field="document_type", required=False, scope="global"),
        MetadataPolicyRule(field="document_type", required=True, scope="department", department_id="legal"),
    ]
    assert is_field_required(rules, "document_type", department_id="legal")
    assert not is_field_required(rules, "document_type", department_id="hr")


def test_global_with_exceptions():
    rules = [
        MetadataPolicyRule(field="department", required=True, scope="global", exceptions=("sandbox",)),
    ]
    assert is_field_required(rules, "department", department_id="hr")
    assert not is_field_required(rules, "department", department_id="sandbox")


def test_validate_metadata_returns_missing_required_fields():
    rules = [
        MetadataPolicyRule(field="department", required=True, scope="global"),
        MetadataPolicyRule(field="project_id", required=False, scope="global"),
    ]
    missing = validate_metadata({"department": None, "project_id": None}, rules, department_id="hr")
    assert missing == ["department"]


def test_validate_metadata_passes_when_required_present():
    rules = [MetadataPolicyRule(field="department", required=True, scope="global")]
    missing = validate_metadata({"department": "hr"}, rules, department_id="hr")
    assert missing == []


def test_validate_metadata_no_rules_means_no_obligations():
    assert validate_metadata({}, [], department_id="hr") == []
