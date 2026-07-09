import json
import os
import tempfile
import time


def _make_store_with_data(db_path):
    from rag.crosscutting.observability.trace_store import SQLiteTraceStore
    store = SQLiteTraceStore(db_path)

    spans = [
        ("search.dense.embed",   "r1", 120.0, {}),
        ("search.dense.embed",   "r1", 150.0, {}),
        ("search.dense.query",   "r1",  80.0, {}),
        ("rerank.cross_encoder", "r1", 300.0, {}),
        ("generate.llm",         "r1", 500.0, {"outcome": "answered"}),
        ("generate.llm",         "r2", 520.0, {"outcome": "declined"}),
        ("generate.llm",         "r3", 510.0, {"outcome": "answered"}),
    ]
    now = time.time()
    for span_name, rid, dur, attrs in spans:
        store.write_span(rid, span_name, None, now, dur, attrs)

    store.write_eval_run("ragas", {"faithfulness": 0.82, "answer_relevancy": 0.88}, "abc1")
    store.write_eval_run("ragas", {"faithfulness": 0.85, "answer_relevancy": 0.90}, "abc2")
    store.write_eval_run("table_regression", {"hit_at_10": 1.0, "mrr": 1.0}, "abc2")
    return store


def test_report_runs_without_error(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = _make_store_with_data(db_path)

        import eval.eval_report as rpt
        monkeypatch.setattr(rpt, "_get_store", lambda: store)

        # Should not raise
        rpt.print_report(store)
        store.conn.close()
    finally:
        os.unlink(db_path)


def test_report_handles_empty_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from rag.crosscutting.observability.trace_store import SQLiteTraceStore
        store = SQLiteTraceStore(db_path)

        import eval.eval_report as rpt
        monkeypatch.setattr(rpt, "_get_store", lambda: store)

        # Empty DB — should not raise, just print "no X recorded"
        rpt.print_report(store)
        store.conn.close()
    finally:
        os.unlink(db_path)
