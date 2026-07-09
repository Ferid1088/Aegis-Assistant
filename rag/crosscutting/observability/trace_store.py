"""TraceStore interface + SQLiteTraceStore.

Sink for @traced span rows and eval run metrics.
Swap to Postgres later: implement TraceStore with psycopg2 and set
observability_db_path accordingly (or add a postgres_dsn setting).
"""

import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from rag.config import settings


class TraceStore(ABC):
    @abstractmethod
    def write_span(
        self,
        request_id: str,
        span_name: str,
        parent_span: str | None,
        started_at: float,
        duration_ms: float,
        attributes: dict[str, Any],
    ) -> None: ...

    @abstractmethod
    def write_eval_run(
        self,
        kind: str,
        metrics: dict[str, Any],
        git_commit: str,
    ) -> str: ...

    @abstractmethod
    def list_eval_runs(self, limit: int = 50) -> list[dict[str, Any]]: ...

    @abstractmethod
    def latency_summary(self, limit_spans: int = 5000) -> list[dict[str, Any]]: ...


class SQLiteTraceStore(TraceStore):
    def __init__(self, db_path: str | None = None) -> None:
        path = Path(db_path or settings.observability_db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id  TEXT NOT NULL,
                span_name   TEXT NOT NULL,
                parent_span TEXT,
                started_at  REAL NOT NULL,
                duration_ms REAL NOT NULL,
                attributes  TEXT NOT NULL DEFAULT '{}',
                ts          TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_traces_span ON traces(span_name);
            CREATE INDEX IF NOT EXISTS idx_traces_rid  ON traces(request_id);

            CREATE TABLE IF NOT EXISTS eval_runs (
                run_id     TEXT PRIMARY KEY,
                kind       TEXT NOT NULL,
                metrics    TEXT NOT NULL DEFAULT '{}',
                git_commit TEXT NOT NULL DEFAULT '',
                ts         TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    def write_span(
        self,
        request_id: str,
        span_name: str,
        parent_span: str | None,
        started_at: float,
        duration_ms: float,
        attributes: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """INSERT INTO traces
               (request_id, span_name, parent_span, started_at, duration_ms, attributes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (request_id, span_name, parent_span, started_at,
             duration_ms, json.dumps(attributes, ensure_ascii=False)),
        )
        self.conn.commit()

    def write_eval_run(
        self,
        kind: str,
        metrics: dict[str, Any],
        git_commit: str,
    ) -> str:
        run_id = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO eval_runs (run_id, kind, metrics, git_commit)
               VALUES (?, ?, ?, ?)""",
            (run_id, kind, json.dumps(metrics, ensure_ascii=False), git_commit),
        )
        self.conn.commit()
        return run_id

    def list_eval_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id, kind, metrics, git_commit, ts FROM eval_runs ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "kind": row["kind"],
                "metrics": json.loads(row["metrics"]),
                "git_commit": row["git_commit"],
                "ts": row["ts"],
            }
            for row in rows
        ]

    def latency_summary(self, limit_spans: int = 5000) -> list[dict[str, Any]]:
        """p50/p95/p99 duration per span_name over the most recent spans."""
        rows = self.conn.execute(
            """SELECT span_name, duration_ms FROM traces
               WHERE id IN (SELECT id FROM traces ORDER BY id DESC LIMIT ?)
               ORDER BY span_name""",
            (limit_spans,),
        ).fetchall()
        by_span: dict[str, list[float]] = {}
        for row in rows:
            by_span.setdefault(row["span_name"], []).append(row["duration_ms"])

        def _pct(values: list[float], pct: float) -> float:
            if not values:
                return 0.0
            s = sorted(values)
            idx = min(len(s) - 1, int(len(s) * pct))
            return s[idx]

        return [
            {
                "span": span,
                "p50": _pct(values, 0.50),
                "p95": _pct(values, 0.95),
                "p99": _pct(values, 0.99),
            }
            for span, values in sorted(by_span.items())
        ]


_store: SQLiteTraceStore | None = None


def get_trace_store() -> SQLiteTraceStore:
    global _store
    if _store is None:
        _store = SQLiteTraceStore()
    return _store
