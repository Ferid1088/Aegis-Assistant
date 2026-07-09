from decimal import Decimal

from rag.capabilities.math_engine import MathEngine, format_decimal_german, parse_decimal
from rag.capabilities.resolve import resolve, resolve_chain
from rag.domain.models import Computation, ComputationStep, RuleArtifact


def _progression_rule() -> RuleArtifact:
    return RuleArtifact(
        rule_kind="progression",
        statement="Allgemeine Stufenlaufzeit nach §16 TV-L",
        consequence="Stufe",
        variables=["years_continuous", "stufe"],
        domain="TV-L",
        source_doc_id="seed",
        source_page=32,
        source_chunk_id="chunk-1",
        source_quote="§16 TV-L Stufenlaufzeit",
        confidence=0.95,
        computation=Computation(
            type="cumulative_steps",
            steps=[
                ComputationStep(from_state="Stufe 1", to_state="Stufe 2", increment=Decimal("1"), unit="years", source_quote="Stufe 2 nach 1 Jahr in Stufe 1", page=32),
                ComputationStep(from_state="Stufe 2", to_state="Stufe 3", increment=Decimal("2"), unit="years", source_quote="Stufe 3 nach 2 Jahren in Stufe 2", page=32),
                ComputationStep(from_state="Stufe 3", to_state="Stufe 4", increment=Decimal("3"), unit="years", source_quote="Stufe 4 nach 3 Jahren in Stufe 3", page=32),
            ],
        ),
    )


def test_parse_and_format_german_currency() -> None:
    parsed = parse_decimal("4.609,96")
    assert parsed == Decimal("4609.96")
    assert format_decimal_german(parsed, "EUR") == "4.609,96 €"


def test_decimal_rounding_prevents_float_style_drift() -> None:
    engine = MathEngine()

    tree = {
        "op": "round",
        "rounding": {"mode": "ROUND_HALF_UP", "quantum": "0.01"},
        "operands": [
            {
                "op": "add",
                "operands": [
                    {"kind": "constant", "value": "0,10", "unit": "EUR"},
                    {"kind": "constant", "value": "0,20", "unit": "EUR"},
                ],
            }
        ],
    }

    result = engine.evaluate(tree)
    assert result.error is None
    assert result.value == Decimal("0.30")
    assert result.formatted == "0,30 €"
    assert float(0.1 + 0.2) != 0.3


def test_percentage_of_is_source_linked() -> None:
    result = resolve(
        rules=[
            RuleArtifact(
                rule_kind="formula",
                statement="80 Prozent eines Monatsentgelts",
                consequence="Teilbetrag",
                variables=["percentage", "base"],
                domain="TV-L",
                source_doc_id="doc-1",
                source_page=9,
                source_chunk_id="chunk-2",
                source_quote="80 Prozent des Tabellenentgelts",
                confidence=0.9,
                computation=Computation(type="percentage_of"),
            )
        ],
        target_variable="amount",
        inputs={
            "percentage": {"kind": "lookup", "value": "80", "unit": "percent", "source_quote": "80 %", "page": 9},
            "base": {"kind": "lookup", "value": "4.609,96", "unit": "EUR", "source_quote": "Tabellenentgelt E12/Stufe 4", "page": 33},
        },
    )

    assert result.resolved is True
    assert result.value == Decimal("3687.968")
    assert result.unit == "EUR"
    assert any(step["op"] == "percentage" for step in result.computation_trace)
    assert any(c.get("source_quote") == "Tabellenentgelt E12/Stufe 4" for c in result.cited_rules)


def test_difference_uses_both_cited_operands() -> None:
    result = resolve(
        rules=[
            RuleArtifact(
                rule_kind="formula",
                statement="Differenz zwischen E9 und KR9a pro Jahr",
                consequence="Jahresdifferenz",
                variables=["left", "right"],
                domain="TV-L",
                source_doc_id="doc-2",
                source_page=17,
                source_chunk_id="chunk-3",
                source_quote="Differenz der Tabellenentgelte",
                confidence=0.9,
                computation=Computation(type="difference"),
            )
        ],
        target_variable="difference",
        inputs={
            "left": {"kind": "lookup", "value": "52.000,00", "unit": "EUR/Jahr", "source_quote": "E9 Jahresbetrag", "page": 17},
            "right": {"kind": "lookup", "value": "49.500,00", "unit": "EUR/Jahr", "source_quote": "KR9a Jahresbetrag", "page": 18},
        },
    )

    assert result.resolved is True
    assert result.value == Decimal("2500.00")
    assert result.formatted == "2.500,00 €/Jahr"
    subtract_step = next(step for step in result.computation_trace if step["op"] == "subtract")
    operand_quotes = {operand.get("source_quote") for operand in subtract_step["operands"]}
    assert operand_quotes == {"E9 Jahresbetrag", "KR9a Jahresbetrag"}


def test_proration_multiplies_ratio_correctly() -> None:
    result = resolve(
        rules=[
            RuleArtifact(
                rule_kind="formula",
                statement="Teilzeitentgelt = Vollzeitentgelt × Beschäftigungsumfang",
                consequence="Teilzeitbetrag",
                variables=["base", "ratio"],
                domain="TV-L",
                source_doc_id="doc-3",
                source_page=12,
                source_chunk_id="chunk-4",
                source_quote="Beschäftigungsumfang anteilig",
                confidence=0.9,
                computation=Computation(type="proration"),
            )
        ],
        target_variable="amount",
        inputs={
            "base": {"kind": "lookup", "value": "4.000,00", "unit": "EUR/Monat", "source_quote": "Vollzeitentgelt", "page": 12},
            "ratio": {"kind": "lookup", "value": "0,5", "unit": "ratio", "source_quote": "50 % Beschäftigungsumfang", "page": 12},
        },
    )

    assert result.resolved is True
    assert result.value == Decimal("2000.000")
    assert result.formatted == "2.000,000 €/Monat"


def test_incompatible_units_return_typed_error_for_gate() -> None:
    result = resolve(
        rules=[
            RuleArtifact(
                rule_kind="formula",
                statement="Unzulässige Summe",
                consequence="Fehler",
                variables=["left", "right"],
                domain="TV-L",
                source_doc_id="doc-4",
                source_page=1,
                source_chunk_id="chunk-5",
                source_quote="nicht addierbar",
                confidence=0.9,
                computation=Computation(type="operator_tree", tree={
                    "op": "add",
                    "operands": [
                        {"kind": "lookup", "value": "4.000,00", "unit": "EUR/Monat", "source_quote": "Monatsbetrag", "page": 1},
                        {"kind": "lookup", "value": "48.000,00", "unit": "EUR/Jahr", "source_quote": "Jahresbetrag", "page": 1},
                    ],
                }),
            )
        ],
        target_variable="invalid",
    )

    assert result.resolved is False
    assert result.math_error is not None
    assert result.math_error.code == "incompatible_units"
    assert result.answerability_action == "gate"


def test_division_by_zero_returns_typed_error_for_gate() -> None:
    result = resolve(
        rules=[
            RuleArtifact(
                rule_kind="formula",
                statement="Entgelt / Beschäftigungsumfang",
                consequence="Fehler bei Null",
                variables=["base", "ratio"],
                domain="TV-L",
                source_doc_id="doc-5",
                source_page=2,
                source_chunk_id="chunk-6",
                source_quote="durch Beschäftigungsumfang teilen",
                confidence=0.9,
                computation=Computation(type="operator_tree", tree={
                    "op": "divide",
                    "operands": [
                        {"kind": "lookup", "value": "4.000,00", "unit": "EUR/Monat", "source_quote": "Entgelt", "page": 2},
                        {"kind": "lookup", "value": "0", "unit": "ratio", "source_quote": "Beschäftigungsumfang 0", "page": 2},
                    ],
                }),
            )
        ],
        target_variable="invalid",
    )

    assert result.resolved is False
    assert result.math_error is not None
    assert result.math_error.code == "division_by_zero"
    assert result.answerability_action == "gate"


def test_resolve_chain_preserves_e12_to_stufe_4_and_amount() -> None:
    def table_lookup(grade: str, stufe: str) -> str | None:
        if grade == "E12" and stufe == "Stufe 4":
            return "4.609,96 €"
        return None

    result = resolve_chain("Was verdient E12 nach 6 Jahren?", [_progression_rule()], table_lookup_fn=table_lookup)

    assert result.resolved is True
    assert result.unit == "EUR"
    assert result.value == Decimal("4609.96")
    assert result.formatted == "4.609,96 €"
    assert any(step["op"] == "cumulative_steps" for step in result.computation_trace)
    assert any(step["op"] == "table_lookup" for step in result.computation_trace)
