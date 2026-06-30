"""Backward-compatibility re-export — extraction now lives in capabilities."""

from rag.capabilities.extract import (  # noqa: F401
    RELATIONS,
    build_rule_chunks,
    extract_entities,
    extract_relations,
    extract_rules,
    process_chunk_graph,
    validate_entities,
    validate_relations,
    validate_rules,
)
