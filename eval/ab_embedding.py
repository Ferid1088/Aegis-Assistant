"""Embedding model A/B comparison.

Usage:
    uv run python eval/ab_embedding.py

Re-index steps (manual, run BEFORE this script):
    # Model A (bge-m3, current collection):
    uv run python run_ingest.py data/TV_L.pdf  # default QDRANT_COLLECTION=documents

    # Model B (e5-instruct):
    QDRANT_COLLECTION=documents_e5 DENSE_EMBEDDING_MODEL=intfloat/multilingual-e5-large-instruct \
      uv run python run_ingest.py data/TV_L.pdf

Both scripts must complete before running this A/B runner.

E5-instruct asymmetry:
    Passage prefix: "passage: <text>"   (applied during ingest)
    Query prefix:   "Instruct: Retrieve relevant German HR/legal documents.\\nQuery: <text>"
    (This script injects the query prefix via DENSE_QUERY_PREFIX env var.)
"""

import json
import os
import sys
from pathlib import Path

# Patch broken langchain_community import before ragas loads
sys.modules.setdefault("langchain_community.chat_models.vertexai", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

import nest_asyncio
nest_asyncio.apply()

from datasets import Dataset
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

GOLDEN_PATH = Path("eval/golden_set.jsonl")

VARIANTS = [
    {
        "model": "bge-m3",
        "collection": "documents",
        "query_prefix": "",
    },
    {
        "model": "intfloat/multilingual-e5-large-instruct",
        "collection": "documents_e5",
        "query_prefix": "Instruct: Retrieve relevant German HR/legal documents.\nQuery: ",
    },
]


def _run_variant(variant: dict, gold: list[dict]) -> dict:
    os.environ["DENSE_EMBEDDING_MODEL"] = variant["model"]
    os.environ["QDRANT_COLLECTION"] = variant["collection"]
    os.environ["DENSE_QUERY_PREFIX"] = variant["query_prefix"]

    # Force reload of cached singletons
    import importlib
    import rag.infra.models.llm as prov
    prov.get_embedder.cache_clear()
    importlib.reload(prov)

    import rag.config
    importlib.reload(rag.config)
    from rag.config import settings as _s
    # Sanity check
    assert _s.qdrant_collection == variant["collection"], (
        f"Collection mismatch: {_s.qdrant_collection} != {variant['collection']}\n"
        "Re-index both collections before running this script."
    )

    from rag.pipelines.retrieval.graph import build_query_graph
    graph = build_query_graph()

    questions, answers, contexts_list, ground_truths = [], [], [], []
    for i, item in enumerate(gold):
        q = item["question"]
        print(f"  [{i+1}/{len(gold)}] {q}")
        try:
            result = graph.invoke({"question": q})
            answer = result.get("answer", "")
            reranked = result.get("reranked", [])
            ctx = [c.content for c in reranked] if reranked else [""]
        except Exception as exc:
            print(f"    ❌ {exc}")
            answer, ctx = "", [""]
        questions.append(q)
        answers.append(answer)
        contexts_list.append(ctx)
        ground_truths.append(item["ground_truth"])

    dataset = Dataset.from_dict({
        "question": questions, "answer": answers,
        "contexts": contexts_list, "ground_truth": ground_truths,
    })
    from rag.infra.models.llm import get_llm, get_embedder

    class _EmbAdapter:
        def __init__(self, e): self._e = e
        def embed_documents(self, ts): return [v.tolist() for v in self._e.embed(ts)]
        def embed_query(self, t): return list(self._e.embed([t]))[0].tolist()

    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=LangchainLLMWrapper(get_llm()),
        embeddings=LangchainEmbeddingsWrapper(_EmbAdapter(get_embedder())),
        show_progress=True,
    )
    df = result.to_pandas()
    metric_cols = [c for c in df.columns if c not in ("question", "answer", "contexts", "ground_truth")]
    scores = {col: float(df[col].dropna().mean()) for col in metric_cols if len(df[col].dropna()) > 0}
    scores["model"] = variant["model"]
    return scores


def main():
    gold = []
    with open(GOLDEN_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    print(f"Loaded {len(gold)} golden questions\n")

    results = []
    for variant in VARIANTS:
        print(f"\n{'='*60}")
        print(f"Running variant: {variant['model']} (collection: {variant['collection']})")
        print('='*60)
        scores = _run_variant(variant, gold)
        results.append(scores)

    print("\n" + "="*60)
    print("A/B RESULTS")
    print("="*60)
    metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    print(f"{'Metric':<25} {'bge-m3':>12} {'e5-instruct':>14} {'delta':>8}")
    print("-"*62)
    for m in metrics:
        a = results[0].get(m, float("nan"))
        b = results[1].get(m, float("nan"))
        delta = b - a
        winner = "▲" if delta > 0.01 else ("▼" if delta < -0.01 else "≈")
        print(f"  {m:<23} {a:>12.4f} {b:>14.4f} {delta:>+7.4f} {winner}")
    print("="*60)
    print("Pick winner by context_recall + faithfulness — NOT by gut feeling.")

    out = Path("eval/results/ab_embedding.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
