"""Ragas evaluation runner — offline with qwen2.5 as judge.

Runs the query pipeline on the golden set, then evaluates with Ragas metrics:
faithfulness, answer_relevancy, context_precision, context_recall.

Usage:
    uv run python eval/run_eval.py
"""

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

# Executed as `uv run python eval/run_eval.py`, Python sets sys.path[0] to this
# script's own directory (eval/), not the repo root -- `rag` isn't an installed
# package (no [build-system] in pyproject.toml), so without this the `from rag...`
# imports below (and the `from eval...` one right after) raise ModuleNotFoundError
# regardless of the caller's cwd. Same fix already applied in eval/eval_report.py
# for the same reason.
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.eval_aggregation import aggregate_metric_columns

# Patch broken langchain_community import before ragas loads
sys.modules["langchain_community.chat_models.vertexai"] = MagicMock()

# Allow nested event loops (Ragas uses async internally)
import nest_asyncio
nest_asyncio.apply()

from datasets import Dataset
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from rag.graphs.query import build_query_graph
from rag.infra.models.llm import get_llm

GOLDEN_PATH = Path("eval/golden_set.jsonl")
RESULTS_DIR = Path("eval/results")


class _EmbeddingAdapter:
    """Adapts our DenseEmbedder to LangChain Embeddings interface for Ragas."""

    def __init__(self, embedder):
        self._embedder = embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._embedder.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return list(self._embedder.embed([text]))[0].tolist()


def main():
    gold = []
    with open(GOLDEN_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    print(f"Loaded {len(gold)} golden questions\n")

    graph = build_query_graph()

    questions = []
    answers = []
    contexts_list = []
    ground_truths = []

    for i, item in enumerate(gold):
        q = item["question"]
        print(f"  [{i + 1}/{len(gold)}] {q}")

        try:
            # build_query_graph() always compiles with a checkpointer attached
            # (rag/graphs/query.py's _make_checkpointer(), InMemorySaver or
            # SqliteSaver) -- LangGraph requires a configurable.thread_id (or
            # checkpoint_ns/checkpoint_id) on every .invoke() once a checkpointer
            # is present, or it raises ValueError("Checkpointer requires one or
            # more of the following 'configurable' keys..."). The production API
            # route (rag/api/routers/conversations.py) already supplies this via
            # the real conversation_id; each golden question here is independent
            # (no cross-turn state needed), so a per-question unique thread_id
            # is enough to satisfy the requirement.
            result = graph.invoke(
                {"question": q}, config={"configurable": {"thread_id": f"eval-{i}"}},
            )
            answer = result.get("answer", "")
            reranked = result.get("reranked", [])
            ctx = [c.content for c in reranked] if reranked else [""]
        except Exception as e:
            print(f"    ❌ Error: {e}")
            answer = ""
            ctx = [""]

        questions.append(q)
        answers.append(answer)
        contexts_list.append(ctx)
        ground_truths.append(item["ground_truth"])

    print(f"\n✅ Generated {len(answers)} answers. Running Ragas evaluation...\n")

    dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
        "ground_truth": ground_truths,
    })

    llm = get_llm()
    wrapped_llm = LangchainLLMWrapper(llm)

    from rag.infra.models.llm import get_embedder
    wrapped_emb = LangchainEmbeddingsWrapper(_EmbeddingAdapter(get_embedder()))

    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=wrapped_llm,
        embeddings=wrapped_emb,
        show_progress=True,
    )

    # Extract scores from EvaluationResult via to_pandas()
    df = result.to_pandas()

    metric_cols = [c for c in df.columns if c not in ("question", "answer", "contexts", "ground_truth")]
    agg_scores = aggregate_metric_columns(df, metric_cols)

    print("\n" + "=" * 60)
    print("RAGAS BASELINE SCORES")
    print("=" * 60)
    for metric, score in agg_scores.items():
        print(f"  {metric:<25} {score:.4f}")
    print("=" * 60)

    # Persist eval run to observability DB
    try:
        from eval.eval_store import write_eval_run
        write_eval_run("ragas", dict(agg_scores))
        print("📊 Eval run saved to observability DB")
    except Exception as e:
        print(f"  ⚠️ Could not save eval run: {e}")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"baseline_{date.today().isoformat()}.json"

    save_scores = dict(agg_scores)
    save_scores["date"] = date.today().isoformat()
    save_scores["num_questions"] = len(gold)
    save_scores["golden_set"] = str(GOLDEN_PATH)

    per_question = []
    for _, row in df.iterrows():
        entry = {"question": row.get("question", "")}
        for col in metric_cols:
            val = row.get(col)
            if val is not None and isinstance(val, float):
                entry[col] = round(val, 4)
        per_question.append(entry)

    output = {"aggregate": save_scores, "per_question": per_question}
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n📄 Results saved to {out_path}")

    # Identify poorly-answered multi-hop questions
    print("\n--- Questions with low scores (target set for graph in 05) ---")
    for entry in per_question:
        ctx_recall = entry.get("context_recall", 1.0)
        faithful = entry.get("faithfulness", 1.0)
        if ctx_recall < 0.5 or faithful < 0.5:
            print(f"  ⚠️  {entry['question']}")
            print(f"      context_recall={ctx_recall:.2f}  faithfulness={faithful:.2f}")


if __name__ == "__main__":
    main()
