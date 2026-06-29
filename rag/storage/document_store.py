import sqlite3
from pathlib import Path

from rag.config import settings
from rag.models import DocumentMeta
from rag.storage.base import DocumentStore


class SQLiteDocumentStore(DocumentStore):
    def __init__(self) -> None:
        db_path = Path(settings.sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id         TEXT PRIMARY KEY,
                filename       TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                num_pages      INTEGER NOT NULL,
                doc_version    TEXT,
                is_current     INTEGER NOT NULL DEFAULT 1,
                superseded_by  TEXT
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_content_hash
            ON documents(content_hash)
        """)
        self.conn.commit()

    def register(self, meta: DocumentMeta) -> bool:
        if self.exists(meta.content_hash):
            return False
        self.conn.execute(
            """INSERT INTO documents
               (doc_id, filename, content_hash, num_pages, doc_version, is_current, superseded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                meta.doc_id,
                meta.filename,
                meta.content_hash,
                meta.num_pages,
                meta.doc_version,
                int(meta.is_current),
                meta.superseded_by,
            ),
        )
        self.conn.commit()
        return True

    def exists(self, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM documents WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return row is not None

    def find_current_by_filename(self, filename: str) -> str | None:
        row = self.conn.execute(
            "SELECT doc_id FROM documents WHERE filename = ? AND is_current = 1",
            (filename,),
        ).fetchone()
        return row["doc_id"] if row else None

    def mark_superseded(self, old_doc_id: str, new_doc_id: str) -> None:
        self.conn.execute(
            """UPDATE documents
               SET is_current = 0, superseded_by = ?
               WHERE doc_id = ?""",
            (new_doc_id, old_doc_id),
        )
        self.conn.commit()
