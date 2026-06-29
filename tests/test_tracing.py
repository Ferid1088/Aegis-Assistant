import json
import os
import tempfile

import pytest


def test_traced_writes_span(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from rag.crosscutting.observability import trace_store as ts_module
        from rag.crosscutting.observability.trace_store import SQLiteTraceStore
        store = SQLiteTraceStore(db_path)
        monkeypatch.setattr(ts_module, "_store", store)

        import rag.crosscutting.observability.tracing as tr_module
        monkeypatch.setattr(tr_module, "_get_store", lambda: store)

        from rag.crosscutting.observability.tracing import traced
        from rag.crosscutting.context import Context

        @traced("search.dense.embed")
        def dummy(x: int, ctx: Context | None = None) -> int:
            return x * 2

        ctx = Context(request_id="test-rid-abc")
        result = dummy(5, ctx=ctx)
        assert result == 10

        rows = store.conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["span_name"] == "search.dense.embed"
        assert row["request_id"] == "test-rid-abc"
        assert row["duration_ms"] > 0
        store.conn.close()
    finally:
        os.unlink(db_path)


def test_set_span_attribute_merges_into_span(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from rag.crosscutting.observability import trace_store as ts_module
        from rag.crosscutting.observability.trace_store import SQLiteTraceStore
        store = SQLiteTraceStore(db_path)
        monkeypatch.setattr(ts_module, "_store", store)

        import rag.crosscutting.observability.tracing as tr_module
        monkeypatch.setattr(tr_module, "_get_store", lambda: store)

        from rag.crosscutting.observability.tracing import traced, set_span_attribute
        from rag.crosscutting.context import Context

        @traced("generate.llm")
        def gen(ctx: Context | None = None) -> dict:
            set_span_attribute("outcome", "answered")
            return {"answer": "hello"}

        ctx = Context(request_id="gen-rid")
        gen(ctx=ctx)

        rows = store.conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        attrs = json.loads(rows[0]["attributes"])
        assert attrs.get("outcome") == "answered"
        store.conn.close()
    finally:
        os.unlink(db_path)
