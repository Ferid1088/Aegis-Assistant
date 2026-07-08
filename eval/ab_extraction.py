"""Extraction model A/B comparison (spec 06-B).

The extraction model controls graph triple quality. This script:
  1. Prints the exact shell commands to re-ingest each variant.
  2. After ingestion, reads entity/relation counts from Neo4j to compute drop rates.
  3. Runs the Ragas eval harness and captures context_recall as the "ragas_recall" proxy.
  4. Prints a comparison table.

Run AFTER completing ingestion for BOTH models:

  # Arm A — qwen2.5:7b (default, current graph):
  BUILD_GRAPH=true EXTRACTION_MODEL=qwen2.5:7b uv run python run_ingest.py data/TV_L.pdf

  # Arm B — phi3:mini (faster, check quality):
  BUILD_GRAPH=true EXTRACTION_MODEL=phi3:mini NEO4J_URI=bolt://localhost:7688 \\
    uv run python run_ingest.py data/TV_L.pdf
  # Note: use a separate Neo4j database/port for arm B to avoid polluting arm A.

Then run:
  uv run python eval/ab_extraction.py
"""

import json
import time
import sys
from pathlib import Path

sys.modules.setdefault(
    "langchain_community.chat_models.vertexai",
    __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(),
)

import nest_asyncio
nest_asyncio.apply()

from datasets import Dataset
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import context_recall

GOLDEN_PATH = Path("eval/golden_set.jsonl")

ARMS = [
    {"model": "qwen2.5:7b",  "neo4j_uri": "bolt://localhost:7687"},
    {"model": "phi3:mini",    "neo4j_uri": "bolt://localhost:7688"},
]


def _count_neo4j(neo4j_uri: str) -> dict:
    """Count entities and relations in the given Neo4j instance."""
    try:
        from neo4j import GraphDatabase
        from rag.config import settings
        driver = GraphDatabase.driver(neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        with driver.session() as sess:
            entity_count = sess.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
            relation_count = sess.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        driver.close()
        return {"entities": entity_count, "relations": relation_count}
    except Exception as exc:
        print(f"  ⚠️  Neo4j count failed ({neo4j_uri}): {exc}")
        return {"entities": None, "relations": None}


def _run_eval_recall(neo4j_uri: str) -> tuple[float, float]:
    """Return (context_recall_mean, seconds_per_question) using current graph."""
    import os
    os.environ["NEO4J_URI"] = neo4j_uri

    import importlib
    import rag.config
    importlib.reload(rag.config)
    from rag.config import settings as _s
    assert _s.neo4j_uri == neo4j_uri

    from rag.pipelines.retrieval.graph import build_query_graph
    from rag.infra.models.llm import get_llm, get_embedder

    graph = build_query_graph()
    gold = []
    with open(GOLDEN_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))

    questions, answers, contexts_list, ground_truths = [], [], [], []
    t0 = time.monotonic()
    for item in gold:
        q = item["question"]
        try:
            result = graph.invoke({"question": q})
            answer = result.get("answer", "")
            reranked = result.get("reranked", [])
            ctx = [c.content for c in reranked] if reranked else [""]
        except Exception:
            answer, ctx = "", [""]
        questions.append(q)
        answers.append(answer)
        contexts_list.append(ctx)
        ground_truths.append(item["ground_truth"])
    elapsed = time.monotonic() - t0
    seconds_per_q = elapsed / max(len(gold), 1)

    dataset = Dataset.from_dict({
        "question": questions, "answer": answers,
        "contexts": contexts_list, "ground_truth": ground_truths,
    })

    class _EmbAdapter:
        def __init__(self, e): self._e = e
        def embed_documents(self, ts): return [v.tolist() for v in self._e.embed(ts)]
        def embed_query(self, t): return list(self._e.embed([t]))[0].tolist()

    result = evaluate(
        dataset=dataset,
        metrics=[context_recall],
        llm=LangchainLLMWrapper(get_llm()),
        embeddings=LangchainEmbeddingsWrapper(_EmbAdapter(get_embedder())),
        show_progress=False,
    )
    df = result.to_pandas()
    recall = float(df["context_recall"].dropna().mean()) if "context_recall" in df.columns else float("nan")
    return recall, seconds_per_q


def main():
    print("Extraction model A/B — spec section 06-B")
    print("="*60)
    print("\nPre-flight: ensure both Neo4j instances are populated.")
    print("  Arm A (qwen2.5:7b): bolt://localhost:7687")
    print("  Arm B (phi3:mini):   bolt://localhost:7688\n")

    # Baseline entity counts from arm A for drop-rate calculation
    base = _count_neo4j(ARMS[0]["neo4j_uri"])

    results = []
    for arm in ARMS:
        print(f"\n--- Arm: {arm['model']} ({arm['neo4j_uri']}) ---")
        counts = _count_neo4j(arm["neo4j_uri"])
        recall, secs = _run_eval_recall(arm["neo4j_uri"])

        entity_drop = (
            round(1 - counts["entities"] / base["entities"], 4)
            if base["entities"] and counts["entities"] is not None
            else float("nan")
        )
        relation_drop = (
            round(1 - counts["relations"] / base["relations"], 4)
            if base["relations"] and counts["relations"] is not None
            else float("nan")
        )

        record = {
            "model": arm["model"],
            "entity_drop_rate": entity_drop,
            "relation_drop_rate": relation_drop,
            "ragas_recall": round(recall, 4),
            "seconds_per_chunk": round(secs, 2),
        }
        results.append(record)
        print(f"  entity_drop_rate:   {entity_drop:.4f}")
        print(f"  relation_drop_rate: {relation_drop:.4f}")
        print(f"  ragas_recall:       {recall:.4f}")
        print(f"  seconds_per_q:      {secs:.2f}s")

    print("\n" + "="*60)
    print("EXTRACTION MODEL A/B RESULTS")
    print("="*60)
    headers = ["model", "entity_drop_rate", "relation_drop_rate", "ragas_recall", "seconds_per_chunk"]
    for h in headers:
        vals = " | ".join(f"{r[h]}" for r in results)
        print(f"  {h:<22} {vals}")
    print("="*60)
    print("\nKeep phi3:mini ONLY if:")
    print("  entity_drop_rate  < 0.10 (≤10% entity loss)")
    print("  relation_drop_rate < 0.10")
    print("  ragas_recall      ≥ qwen2.5:7b score")

    out = Path("eval/results/ab_extraction.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n📄 Results saved to {out}")


if __name__ == "__main__":
    main()
