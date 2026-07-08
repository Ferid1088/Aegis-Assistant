"""Extraction capability — entity, relation, and rule extraction from chunks.

Callable standalone (no LangGraph required). Used by ingestion pipeline.
"""

import json
import uuid

from rag.crosscutting.context import Context
from rag.crosscutting.observability.tracing import traced
from rag.infra.models.llm import get_extraction_llm
from rag.models import ChunkRecord, RuleArtifact

RELATIONS = [
    "eingruppiert_in", "gehoert_zu", "erfordert", "monatsentgelt",
    "hebt_sich_heraus_aus", "differenz_zu", "gilt_fuer", "reguliert_durch",
]

ENTITY_PROMPT = """\
Extract named entities from this German document chunk. For each entity provide:
- "name": the entity as it appears in the text
- "canonical": a normalized, canonical German form (merge variants like \
"Krankenpflegerin" / "Gesundheits- und Krankenpflegerinnen" → "Krankenpfleger_in")
- "type": one of "job_title", "salary_level", "entgeltgruppe", "organization", \
"regulation", "concept", "requirement", "document"

Return ONLY a JSON array. If no entities, return [].

Chunk:
{chunk_text}
"""

RELATION_PROMPT = """\
Given these entities extracted from a German document chunk, extract relations between them.

Entities: {entities}

Use ONLY these relation types: {relations}

For each relation provide:
- "from_entity": canonical name of the source entity
- "to_entity": canonical name of the target entity
- "relation_type": one of the allowed types above
- "confidence": 0-1

Return ONLY a JSON array. If no relations, return [].

Chunk:
{chunk_text}
"""

RULE_PROMPT = """\
You extract DECISION RULES from a document chunk. A rule lets a reader DERIVE a \
conclusion from conditions: thresholds, mappings, formulas, eligibility, deadlines, \
prohibitions, defaults. Extract ONLY rules explicitly stated. Do NOT invent or add \
domain knowledge.

For each rule output:
- rule_kind: one of "threshold","mapping","formula","eligibility","deadline","prohibition","default"
- statement: SELF-CONTAINED natural language (resolve pronouns, include scope inline)
- conditions: [{{"variable": str, "operator": str, "value": str, "unit": str or null}}] or []
- condition_logic: "all" or "any"
- consequence: what follows
- variables: list of snake_case variable names the rule involves
- scope: [{{"variable": str, "operator": "==", "value": str}}] for region/time limits, or []
- domain: the domain this rule belongs to
- source_quote: ≤15 words copied verbatim from the chunk
- confidence: 0-1

Return ONLY a JSON array. If no rule, return [].

Chunk:
{chunk_text}
"""


def _parse_json_response(content: str) -> list[dict]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except (json.JSONDecodeError, IndexError):
        pass
    return []


@traced("extract.entities")
def extract_entities(chunk_text: str, ctx: Context | None = None) -> list[dict]:
    llm = get_extraction_llm()
    prompt = ENTITY_PROMPT.format(chunk_text=chunk_text)
    response = llm.invoke(prompt)
    return _parse_json_response(response.content)


@traced("extract.relations")
def extract_relations(chunk_text: str, entities: list[dict],
                      ctx: Context | None = None) -> list[dict]:
    if len(entities) < 2:
        return []
    llm = get_extraction_llm()
    ent_names = [e.get("canonical", e.get("name", "")) for e in entities]
    prompt = RELATION_PROMPT.format(
        chunk_text=chunk_text,
        entities=json.dumps(ent_names, ensure_ascii=False),
        relations=", ".join(RELATIONS),
    )
    response = llm.invoke(prompt)
    return _parse_json_response(response.content)


@traced("extract.rules")
def extract_rules(chunk_text: str, ctx: Context | None = None) -> list[dict]:
    llm = get_extraction_llm()
    prompt = RULE_PROMPT.format(chunk_text=chunk_text)
    response = llm.invoke(prompt)
    return _parse_json_response(response.content)


def validate_entities(raw: list) -> list[dict]:
    valid = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        if not e.get("name") and not e.get("canonical"):
            continue
        if "canonical" not in e:
            e["canonical"] = e["name"]
        valid.append(e)
    return valid


def validate_relations(raw: list, entity_canonicals: set[str]) -> list[dict]:
    valid = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        if not r.get("from_entity") or not r.get("to_entity") or not r.get("relation_type"):
            continue
        if r["relation_type"] not in RELATIONS:
            continue
        if r["from_entity"] not in entity_canonicals or r["to_entity"] not in entity_canonicals:
            continue
        valid.append(r)
    return valid


def validate_rules(raw: list[dict], chunk_id: str, doc_id: str, page: int,
                   doc_version: str | None) -> list[RuleArtifact]:
    valid = []
    for r in raw:
        try:
            rule = RuleArtifact(
                statement=r.get("statement", ""),
                rule_kind=r.get("rule_kind", "default"),
                conditions=[],
                condition_logic=r.get("condition_logic", "all"),
                consequence=r.get("consequence", ""),
                variables=r.get("variables", []),
                scope=[],
                domain=r.get("domain", ""),
                source_doc_id=doc_id,
                source_page=page,
                source_chunk_id=chunk_id,
                source_quote=r.get("source_quote", "")[:200],
                doc_version=doc_version,
                confidence=float(r.get("confidence", 0.5)),
            )
            if not rule.statement or not rule.consequence:
                continue
            valid.append(rule)
        except Exception:
            continue
    return valid


def process_chunk_graph(
    chunk_text: str,
    chunk_id: str,
    doc_id: str,
    page: int,
    doc_version: str | None,
    graph_store,
    prev_chunk_text: str | None = None,
    ctx: Context | None = None,
) -> dict:
    empty = {"entities": 0, "relations": 0, "rules": 0,
             "dropped_entities": 0, "dropped_relations": 0, "dropped_rules": 0,
             "rule_artifacts": []}
    try:
        context = f"{prev_chunk_text}\n\n{chunk_text}" if prev_chunk_text else chunk_text

        raw_ents = extract_entities(context, ctx=ctx)
        ents = validate_entities(raw_ents)

        for e in ents:
            e["doc_id"] = doc_id
            e["chunk_id"] = chunk_id
            e["page"] = page
            e["doc_version"] = doc_version

        if ents:
            graph_store.upsert_entities(ents)

        entity_canonicals = {e["canonical"] for e in ents}
        raw_rels = extract_relations(context, ents, ctx=ctx)
        rels = validate_relations(raw_rels, entity_canonicals)

        for r in rels:
            r["doc_id"] = doc_id
            r["chunk_id"] = chunk_id
            r["page"] = page
            r["doc_version"] = doc_version

        if rels:
            graph_store.upsert_relations(rels)

        raw_rules = extract_rules(chunk_text, ctx=ctx)
        rules = validate_rules(raw_rules, chunk_id, doc_id, page, doc_version)

        return {
            "entities": len(ents),
            "relations": len(rels),
            "rules": len(rules),
            "dropped_entities": len(raw_ents) - len(ents),
            "dropped_relations": len(raw_rels) - len(rels),
            "dropped_rules": len(raw_rules) - len(rules),
            "rule_artifacts": rules,
        }
    except Exception as e:
        print(f"    ⚠️ Graph extraction error: {e}")
        return empty


def build_rule_chunks(rules: list[RuleArtifact]) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            chunk_id=str(uuid.uuid4()),
            type="rule",
            content=rule.statement,
            source_file="",
            doc_id=rule.source_doc_id,
            doc_version=rule.doc_version,
            page_numbers=[rule.source_page],
            heading_path=[],
            bboxes=[],
            keywords=rule.variables,
            summary=rule.consequence,
        )
        for rule in rules
    ]
