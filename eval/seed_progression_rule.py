"""Seed the general §16 TV-L Stufenlaufzeit rule into Qdrant.

This rule was in the source text but extraction attributed it to a specific occupation.
The correct scope is GENERAL (applies to all Entgeltgruppen unless a Tarifteil-specific
rule overrides it). This script inserts it as a structured, computable rule chunk.
"""

import json
import uuid

from rag.llm.provider import get_embedder, get_sparse_embedder
from rag.models import ChunkRecord, Computation, ComputationStep
from rag.storage.vector_store import QdrantVectorStore


def seed():
    computation = Computation(
        type="cumulative_steps",
        steps=[
            ComputationStep(from_state="Stufe 1", to_state="Stufe 2", increment=1, unit="years",
                            source_quote="Stufe 2 nach 1 Jahr in Stufe 1", page=32),
            ComputationStep(from_state="Stufe 2", to_state="Stufe 3", increment=2, unit="years",
                            source_quote="Stufe 3 nach 2 Jahren in Stufe 2", page=32),
            ComputationStep(from_state="Stufe 3", to_state="Stufe 4", increment=3, unit="years",
                            source_quote="Stufe 4 nach 3 Jahren in Stufe 3", page=32),
            ComputationStep(from_state="Stufe 4", to_state="Stufe 5", increment=4, unit="years",
                            source_quote="Stufe 5 nach 4 Jahren in Stufe 4", page=32),
            ComputationStep(from_state="Stufe 5", to_state="Stufe 6", increment=5, unit="years",
                            source_quote="Stufe 6 nach 5 Jahren in Stufe 5", page=32),
        ],
        scope={"regulation": "§16 TV-L", "applies_to": "general",
               "overridden_by": ["Tarifteil-specific progressions"]},
    )

    statement = (
        "Allgemeine Stufenlaufzeit nach §16 TV-L: "
        "Stufe 2 nach 1 Jahr, Stufe 3 nach 2 Jahren, Stufe 4 nach 3 Jahren, "
        "Stufe 5 nach 4 Jahren, Stufe 6 nach 5 Jahren in der jeweiligen Vorstufe. "
        "Kumulativ: 1+2+3=6 Jahre bis Stufe 4, 1+2+3+4=10 Jahre bis Stufe 5, "
        "1+2+3+4+5=15 Jahre bis Stufe 6. "
        "Gilt für alle Entgeltgruppen, sofern kein Tarifteil-spezifischer Stufenaufstieg vorliegt."
    )

    chunk = ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        type="rule",
        content=statement,
        source_file="TV_L.pdf",
        doc_id="seed",
        doc_version="TV-L 2018",
        page_numbers=[32],
        heading_path=["§16 TV-L Stufenlaufzeit"],
        bboxes=[],
        keywords=["stufe", "stufenlaufzeit", "years_continuous", "progression",
                   "§16", "TV-L", "allgemein", "general"],
        summary="Allgemeine Stufenlaufzeit: 1+2+3+4+5 Jahre pro Stufe",
    )

    store = QdrantVectorStore()
    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()

    dense = [v.tolist() for v in embedder.embed([chunk.content])]
    sparse = [{"indices": sv.indices.tolist(), "values": sv.values.tolist()}
              for sv in sparse_embedder.embed([chunk.content])]

    store.upsert([chunk], dense, sparse)

    # Save the computation JSON alongside for the resolver to load
    rule_data = {
        "chunk_id": chunk.chunk_id,
        "rule_kind": "progression",
        "computation": computation.model_dump(),
        "statement": statement,
        "scope": {"regulation": "§16 TV-L", "applies_to": "general"},
        "variables": ["years_continuous", "stufe"],
    }
    rule_path = "data/progression_rules.json"
    import os
    os.makedirs("data", exist_ok=True)
    with open(rule_path, "w") as f:
        json.dump([rule_data], f, indent=2, ensure_ascii=False)

    store.client.close()
    print(f"✅ Seeded §16 progression rule (chunk_id={chunk.chunk_id[:12]})")
    print(f"   Statement: {statement[:80]}...")
    print(f"   Computation: {len(computation.steps)} steps (cumulative_steps)")
    print(f"   Saved to {rule_path}")


if __name__ == "__main__":
    seed()
