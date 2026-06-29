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


_store: SQLiteTraceStore | None = None


def get_trace_store() -> SQLiteTraceStore:
    global _store
    if _store is None:
        _store = SQLiteTraceStore()
    return _store
