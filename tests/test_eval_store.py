import json
import os
import tempfile


def test_write_eval_run_captures_git_commit(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from rag.crosscutting.observability import trace_store as ts_module
        from rag.crosscutting.observability.trace_store import SQLiteTraceStore
        store = SQLiteTraceStore(db_path)
        monkeypatch.setattr(ts_module, "_store", store)

        import eval.eval_store as es
        monkeypatch.setattr(es, "_get_store", lambda: store)
        monkeypatch.setattr(es, "_git_commit", lambda: "deadbeef")

        run_id = es.write_eval_run("ragas", {"faithfulness": 0.9})
        assert run_id

        rows = store.conn.execute("SELECT * FROM eval_runs").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "ragas"
        assert row["git_commit"] == "deadbeef"
        metrics = json.loads(row["metrics"])
        assert metrics["faithfulness"] == 0.9
        store.conn.close()
    finally:
        os.unlink(db_path)
