import json
import os
import tempfile
import time

import pytest


def test_write_and_query_span():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from rag.crosscutting.observability.trace_store import SQLiteTraceStore
        store = SQLiteTraceStore(db_path)
        store.write_span(
            request_id="req-001",
            span_name="search.dense.embed",
            parent_span=None,
            started_at=time.time(),
            duration_ms=12.5,
            attributes={"model": "bge-m3", "tokens": 32},
        )
        rows = store.conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["request_id"] == "req-001"
        assert row["span_name"] == "search.dense.embed"
        assert row["duration_ms"] == pytest.approx(12.5)
        attrs = json.loads(row["attributes"])
        assert attrs["model"] == "bge-m3"
        store.conn.close()
    finally:
        os.unlink(db_path)


def test_write_eval_run():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from rag.crosscutting.observability.trace_store import SQLiteTraceStore
        store = SQLiteTraceStore(db_path)
        run_id = store.write_eval_run(
            kind="ragas",
            metrics={"faithfulness": 0.85, "answer_relevancy": 0.91},
            git_commit="abc1234",
        )
        assert run_id
        rows = store.conn.execute("SELECT * FROM eval_runs").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "ragas"
        metrics = json.loads(row["metrics"])
        assert metrics["faithfulness"] == pytest.approx(0.85)
        assert row["git_commit"] == "abc1234"
        store.conn.close()
    finally:
        os.unlink(db_path)
