"""CLI overview report: latency percentiles, Ragas scores, hit@10, behavior rates.

Usage:
    uv run python eval/eval_report.py

TODO (Phase 8 / UI): expose these aggregations via
  GET /api/v1/admin/evaluation/latency
  GET /api/v1/admin/evaluation/ragas
  GET /api/v1/admin/evaluation/table
  GET /api/v1/admin/evaluation/behavior
and render them in the React Evaluation tab.
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.crosscutting.observability.trace_store import get_trace_store

SPAN_ORDER = [
    "search.dense.embed",
    "search.dense.query",
    "search.sparse.query",
    "search.graph.traverse",
    "search.fusion.rrf",
    "rerank.cross_encoder",
    "extract.entities",
    "extract.relations",
    "extract.rules",
    "generate.llm",
]


def _get_store():
    return get_trace_store()


def print_report(store=None) -> None:
    if store is None:
        store = _get_store()
    conn = store.conn

    print()
    print("=" * 65)
    print("  EVALUATION REPORT")
    print("=" * 65)

    # ── Latency percentiles per span ─────────────────────────────────
    print("\n── Latency (ms) by span  [p50 / p95 / p99] ─────────────────")
    rows = conn.execute("SELECT span_name, duration_ms FROM traces").fetchall()
    by_span: dict[str, list[float]] = {}
    for row in rows:
        by_span.setdefault(row["span_name"], []).append(row["duration_ms"])

    if not by_span:
        print("  (no spans recorded yet)")
    else:
        all_spans = SPAN_ORDER + sorted(s for s in by_span if s not in SPAN_ORDER)
        for span in all_spans:
            vals = by_span.get(span)
            if not vals:
                continue
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            p50 = statistics.median(vals_sorted)
            p95 = vals_sorted[min(int(n * 0.95), n - 1)]
            p99 = vals_sorted[min(int(n * 0.99), n - 1)]
            print(f"  {span:<30}  {p50:>8.1f} / {p95:>8.1f} / {p99:>8.1f}   (n={n})")

    # ── Latest Ragas scores + trend ───────────────────────────────────
    print("\n── Ragas scores (latest vs previous) ────────────────────────")
    ragas_rows = conn.execute(
        "SELECT metrics FROM eval_runs WHERE kind = 'ragas' ORDER BY ts DESC LIMIT 2"
    ).fetchall()
    if not ragas_rows:
        print("  (no ragas runs recorded yet)")
    else:
        latest = json.loads(ragas_rows[0]["metrics"])
        prev = json.loads(ragas_rows[1]["metrics"]) if len(ragas_rows) > 1 else {}
        for k in sorted(latest.keys()):
            val = latest.get(k)
            if not isinstance(val, (int, float)):
                continue
            p = prev.get(k)
            if p is not None and isinstance(p, (int, float)):
                delta = val - p
                trend = f"  Δ{delta:+.4f}"
            else:
                trend = "  (no prev)"
            print(f"  {k:<30}  {val:.4f}{trend}")

    # ── Latest table_regression hit@10 ───────────────────────────────
    print("\n── Table regression (latest hit@10) ─────────────────────────")
    tbl_row = conn.execute(
        "SELECT metrics FROM eval_runs WHERE kind = 'table_regression' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if not tbl_row:
        print("  (no table_regression runs recorded yet)")
    else:
        tm = json.loads(tbl_row["metrics"])
        hit = tm.get("hit_at_10") or tm.get("b_hit_at_10")
        mrr = tm.get("mrr") or tm.get("b_mrr")
        print(f"  hit@10  {hit:.3f}" if hit is not None else "  hit@10  n/a")
        print(f"  mrr     {mrr:.3f}" if mrr is not None else "  mrr     n/a")

    # ── Behavior: outcome rates ───────────────────────────────────────
    print("\n── Behavior rates (from generate.llm spans) ─────────────────")
    gen_rows = conn.execute(
        "SELECT attributes FROM traces WHERE span_name = 'generate.llm'"
    ).fetchall()
    if not gen_rows:
        print("  (no generate.llm spans recorded yet)")
    else:
        counts: dict[str, int] = {"answered": 0, "declined": 0, "fallback": 0, "unknown": 0}
        miss_count = 0
        for row in gen_rows:
            attrs = json.loads(row["attributes"])
            outcome = attrs.get("outcome", "unknown")
            counts[outcome] = counts.get(outcome, 0) + 1
            if attrs.get("retrieval_miss"):
                miss_count += 1
        total = len(gen_rows)
        for outcome in ["answered", "declined", "fallback", "unknown"]:
            c = counts.get(outcome, 0)
            print(f"  {outcome:<12}  {c:>5}  ({c / total:.1%})")
        print(f"  retrieval_miss  {miss_count:>5}  ({miss_count / total:.1%})")

    print()
    print("=" * 65)


if __name__ == "__main__":
    print_report()
