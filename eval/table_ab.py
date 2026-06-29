"""A/B eval harness: retrieval-level comparison of collection A vs B.

Runs the SAME path as production up to rerank:
  transform_query -> dense + sparse -> RRF -> cross-encoder rerank -> top-10
Then checks if the expected answer appears in the reranked results.

Usage:
  uv run python eval/table_ab.py
"""

import json
import re
from datetime import date
from pathlib import Path

from qdrant_client import QdrantClient, models as qm
from sentence_transformers import CrossEncoder

from rag.config import settings
from rag.llm.provider import get_device, get_embedder, get_llm, get_sparse_embedder
from rag.models import RetrievedChunk

GOLD_PATH = Path("eval/table_gold.jsonl")
COLLECTION_A = settings.qdrant_collection
COLLECTION_B = settings.qdrant_collection + "_tabstruct"


def rrf(result_lists: list[list[RetrievedChunk]], k: int = 60) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    by_id: dict[str, RetrievedChunk] = {}
    for lst in result_lists:
        for rank, ch in enumerate(lst):
            scores[ch.chunk_id] = scores.get(ch.chunk_id, 0) + 1.0 / (k + rank)
            by_id[ch.chunk_id] = ch
    ranked = sorted(scores, key=scores.get, reverse=True)
    return [by_id[cid] for cid in ranked]


def search_dense(client, collection, vec, k, flt=None):
    query_filter = None
    if flt:
        conditions = [qm.FieldCondition(key=key, match=qm.MatchValue(value=val)) for key, val in flt.items()]
        query_filter = qm.Filter(must=conditions)
    results = client.query_points(
        collection_name=collection,
        query=vec,
        using="dense",
        limit=k,
        query_filter=query_filter,
        with_payload=True,
    ).points
    return [_to_retrieved(hit) for hit in results]


def search_sparse(client, collection, vec, k, flt=None):
    query_filter = None
    if flt:
        conditions = [qm.FieldCondition(key=key, match=qm.MatchValue(value=val)) for key, val in flt.items()]
        query_filter = qm.Filter(must=conditions)
    sparse_vector = qm.SparseVector(indices=vec["indices"], values=vec["values"])
    results = client.query_points(
        collection_name=collection,
        query=sparse_vector,
        using="sparse",
        limit=k,
        query_filter=query_filter,
        with_payload=True,
    ).points
    return [_to_retrieved(hit) for hit in results]


def _to_retrieved(hit) -> RetrievedChunk:
    payload = hit.payload or {}
    return RetrievedChunk(
        chunk_id=payload.get("chunk_id", str(hit.id)),
        content=payload.get("content", ""),
        score=hit.score if hit.score is not None else 0.0,
        metadata=payload,
    )


def transform_query(question: str) -> tuple[str, str]:
    llm = get_llm()
    prompt = (
        'You are a search query optimizer for German legal/HR documents (TV-L). '
        'Given a user question, produce a JSON object with two fields: '
        '"rewritten" (precise German technical terms) and "expanded" (German synonyms). '
        'Output ONLY valid JSON.\nQuestion: ' + question
    )
    resp = llm.invoke(prompt)
    text = resp.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
        return parsed.get("rewritten", question), parsed.get("expanded", question)
    except (json.JSONDecodeError, AttributeError, IndexError):
        return question, question


def run_retrieval(client, collection, question, rewritten, expanded):
    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()

    # Dense
    vecs = [v.tolist() for v in embedder.embed([question, rewritten])]
    dense_hits = [search_dense(client, collection, v, settings.dense_top_k) for v in vecs]
    dense_results = rrf(dense_hits, k=settings.rrf_k)

    # Sparse
    svecs = list(sparse_embedder.embed([question, expanded]))
    sparse_hits = [
        search_sparse(client, collection,
                      {"indices": sv.indices.tolist(), "values": sv.values.tolist()},
                      settings.sparse_top_k)
        for sv in svecs
    ]
    sparse_results = rrf(sparse_hits, k=settings.rrf_k)

    # RRF fuse
    fused = rrf([dense_results, sparse_results], k=settings.rrf_k)
    candidates = fused[:settings.fusion_candidates]

    return candidates


def run_rerank(reranker, question, candidates):
    if not candidates:
        return []
    pairs = [[question, c.content] for c in candidates]
    scores = reranker.predict(pairs)
    reranked = []
    for c, s in zip(candidates, scores):
        reranked.append(RetrievedChunk(
            chunk_id=c.chunk_id, content=c.content,
            score=float(s), metadata=c.metadata,
        ))
    reranked.sort(key=lambda c: c.score, reverse=True)
    return reranked


def is_hit(chunk: RetrievedChunk, grade: str, expected_amount: str) -> bool:
    content = chunk.content
    grade_compact = grade.replace(" ", "")
    grade_match = grade in content or grade_compact in content
    amount_nodot = expected_amount.replace(".", "")
    amount_match = expected_amount in content or amount_nodot in content
    return grade_match and amount_match


def eval_collection(client, collection, gold, reranker):
    results = []
    for item in gold:
        q = item["question"]
        grade = item["grade"]
        expected = item["expected_amount"]

        rewritten, expanded = transform_query(q)
        candidates = run_retrieval(client, collection, q, rewritten, expanded)
        reranked = run_rerank(reranker, q, candidates)

        top10 = reranked[:10]
        top5 = reranked[:5]

        first_hit_rank = 999
        for rank, ch in enumerate(top10):
            if is_hit(ch, grade, expected):
                first_hit_rank = rank + 1
                break

        hit_at_10 = 1 if first_hit_rank <= 10 else 0
        hit_at_5 = 1 if first_hit_rank <= 5 else 0
        mrr = 1.0 / first_hit_rank if first_hit_rank <= 10 else 0.0

        top3_snippets = [ch.content[:100] for ch in top10[:3]]

        results.append({
            "question": q,
            "grade": grade,
            "stufe": item["stufe"],
            "expected_amount": expected,
            "hit_at_10": hit_at_10,
            "hit_at_5": hit_at_5,
            "mrr": mrr,
            "first_hit_rank": first_hit_rank,
            "top3_snippets": top3_snippets,
        })

        status = f"HIT@{first_hit_rank}" if first_hit_rank <= 10 else "MISS"
        print(f"  {status:8s}  {q}")

    return results


def aggregate(results):
    n = len(results)
    return {
        "hit_at_10": sum(r["hit_at_10"] for r in results) / n,
        "hit_at_5": sum(r["hit_at_5"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
        "mean_rank": sum(r["first_hit_rank"] for r in results) / n,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default=None,
                        help="Single collection to eval (default: run A vs B comparison)")
    args = parser.parse_args()

    gold = []
    with open(GOLD_PATH) as f:
        for line in f:
            gold.append(json.loads(line))
    print(f"Loaded {len(gold)} gold questions\n")

    client = QdrantClient(path=settings.qdrant_path)
    dev = get_device()
    reranker = CrossEncoder(settings.reranker_model, device=dev)

    if args.collection:
        coll = args.collection
        print(f"=== Evaluating {coll} ===")
        results = eval_collection(client, coll, gold, reranker)
        agg = aggregate(results)
        client.close()

        print("\n" + "=" * 50)
        print(f"{'Metric':<20} {'Value':>12}")
        print("-" * 50)
        for metric in ["hit_at_10", "hit_at_5", "mrr", "mean_rank"]:
            print(f"{metric:<20} {agg[metric]:>12.3f}")
        print("=" * 50)

        e12 = next((r for r in results if ("E 12" in r["grade"] or "E12" in r["question"]) and r["stufe"] == "4"), None)
        if e12:
            print(f"\nE12/Stufe4: {'HIT@' + str(e12['first_hit_rank']) if e12['hit_at_10'] else 'MISS'}")

        results_dir = Path("eval/results")
        results_dir.mkdir(exist_ok=True)
        out_path = results_dir / f"table_eval_{coll}_{date.today().isoformat()}.md"
        with open(out_path, "w") as f:
            f.write(f"# Eval: {coll}\n\nDate: {date.today().isoformat()}\n\n")
            f.write(f"| Metric | Value |\n|--------|-------|\n")
            for metric in ["hit_at_10", "hit_at_5", "mrr", "mean_rank"]:
                f.write(f"| {metric} | {agg[metric]:.3f} |\n")
            f.write(f"\n## Per-Question\n\n")
            f.write("| Question | Grade | Stufe | Expected | Hit@10 | Rank | Top-3 snippets |\n")
            f.write("|----------|-------|-------|----------|--------|------|----------------|\n")
            for r in results:
                snippets = " // ".join(s.replace("|", "\\|").replace("\n", " ")[:60] for s in r["top3_snippets"])
                rank = str(r["first_hit_rank"]) if r["first_hit_rank"] <= 10 else "MISS"
                f.write(f"| {r['question']} | {r['grade']} | {r['stufe']} | {r['expected_amount']} | "
                        f"{r['hit_at_10']} | {rank} | {snippets} |\n")
        print(f"\n📄 Results saved to {out_path}")

        # Persist to observability DB
        try:
            from eval.eval_store import write_eval_run
            write_eval_run("table_regression", {"collection": coll, **agg})
            print("📊 Eval run saved to observability DB")
        except Exception as e:
            print(f"  ⚠️ Could not save eval run: {e}")
        return

    # A/B comparison mode (original behavior)
    print(f"=== Variant A ({COLLECTION_A}) ===")
    results_a = eval_collection(client, COLLECTION_A, gold, reranker)
    agg_a = aggregate(results_a)

    print(f"\n=== Variant B ({COLLECTION_B}) ===")
    results_b = eval_collection(client, COLLECTION_B, gold, reranker)
    agg_b = aggregate(results_b)

    client.close()

    print("\n" + "=" * 70)
    print(f"{'Metric':<20} {'Variant A':>12} {'Variant B':>12} {'Delta':>12}")
    print("-" * 70)
    for metric in ["hit_at_10", "hit_at_5", "mrr", "mean_rank"]:
        a_val = agg_a[metric]
        b_val = agg_b[metric]
        delta = b_val - a_val
        sign = "+" if delta > 0 else ""
        print(f"{metric:<20} {a_val:>12.3f} {b_val:>12.3f} {sign}{delta:>11.3f}")
    print("=" * 70)

    e12_a = next((r for r in results_a if ("E 12" in r["grade"] or "E12" in r["question"]) and r["stufe"] == "4"), None)
    e12_b = next((r for r in results_b if ("E 12" in r["grade"] or "E12" in r["question"]) and r["stufe"] == "4"), None)
    e12_fixed = e12_b and e12_b["hit_at_10"] == 1 and (not e12_a or e12_a["hit_at_10"] == 0)
    agg_improved = agg_b["hit_at_10"] > agg_a["hit_at_10"]

    print(f"\nE12/Stufe4 in A: {'HIT@' + str(e12_a['first_hit_rank']) if e12_a and e12_a['hit_at_10'] else 'MISS'}")
    print(f"E12/Stufe4 in B: {'HIT@' + str(e12_b['first_hit_rank']) if e12_b and e12_b['hit_at_10'] else 'MISS'}")
    print(f"\nVERDICT: B {'FIXES' if e12_fixed else 'does NOT fix'} E12/Stufe4, "
          f"aggregate hit@10 {'IMPROVES' if agg_improved else 'does NOT improve'} "
          f"({agg_a['hit_at_10']:.0%} → {agg_b['hit_at_10']:.0%})")

    # Persist to observability DB
    try:
        from eval.eval_store import write_eval_run
        write_eval_run("table_regression", {
            "collection_a": COLLECTION_A,
            "collection_b": COLLECTION_B,
            **{f"a_{k}": v for k, v in agg_a.items()},
            **{f"b_{k}": v for k, v in agg_b.items()},
        })
        print("📊 Eval run saved to observability DB")
    except Exception as e:
        print(f"  ⚠️ Could not save eval run: {e}")


if __name__ == "__main__":
    main()
