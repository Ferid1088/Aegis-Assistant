import json
import sqlite3
import uuid
from pathlib import Path

from rag.config import settings
from rag.domain.document_lifecycle import (
    DocumentVersion,
    LogicalDocument,
    LogicalDocumentState,
    ProcessingState,
)
from rag.models import DocumentMeta
from rag.infra.stores.base import DocumentStore


class SQLiteDocumentStore(DocumentStore):
    def __init__(self, db_path: str | None = None) -> None:
        path = Path(db_path or settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.isolation_level = None  # manual transaction control (02.1 §2.2 atomic version allocation)
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
        # ── 02.1: logical document / version split ───────────────────────
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS logical_documents (
                logical_doc_id  TEXT PRIMARY KEY,
                source_identity TEXT NOT NULL UNIQUE,
                tenant_id       TEXT NOT NULL DEFAULT 'default',
                department      TEXT,
                access_level    TEXT NOT NULL DEFAULT '[]',
                document_type   TEXT,
                project_id      TEXT,
                phase_id        TEXT,
                state           TEXT NOT NULL DEFAULT 'active',
                created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS document_versions (
                version_id        TEXT PRIMARY KEY,
                logical_doc_id    TEXT NOT NULL REFERENCES logical_documents(logical_doc_id),
                version_no        INTEGER NOT NULL,
                content_hash      TEXT NOT NULL,
                filename          TEXT NOT NULL,
                num_pages         INTEGER NOT NULL DEFAULT 0,
                is_active         INTEGER NOT NULL DEFAULT 1,
                processing_state  TEXT NOT NULL DEFAULT 'queued',
                created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(logical_doc_id, version_no)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id       TEXT PRIMARY KEY,
                name             TEXT NOT NULL,
                default_metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS phases (
                phase_id         TEXT PRIMARY KEY,
                project_id       TEXT NOT NULL REFERENCES projects(project_id),
                parent_phase_id  TEXT REFERENCES phases(phase_id),
                name             TEXT NOT NULL,
                default_metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self._ensure_column("logical_documents", "created_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        self._ensure_column("document_versions", "created_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        self._ensure_column("document_versions", "updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")

    # ── original 02 flow — unchanged behavior ─────────────────────────────

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

    # ── 02.1: logical document / version split ────────────────────────────

    def find_logical_by_identity(self, source_identity: str) -> str | None:
        row = self.conn.execute(
            "SELECT logical_doc_id FROM logical_documents WHERE source_identity = ?",
            (source_identity,),
        ).fetchone()
        return row["logical_doc_id"] if row else None

    def create_logical_document(self, doc: LogicalDocument) -> None:
        self.conn.execute(
            """INSERT INTO logical_documents
               (logical_doc_id, source_identity, tenant_id, department, access_level,
                document_type, project_id, phase_id, state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc.logical_doc_id, doc.source_identity, doc.tenant_id, doc.department,
                json.dumps(doc.access_level), doc.document_type, doc.project_id, doc.phase_id,
                doc.state.value, doc.created_at.isoformat(),
            ),
        )

    def get_logical_document(self, logical_doc_id: str) -> LogicalDocument | None:
        row = self.conn.execute(
            """SELECT logical_doc_id, source_identity, tenant_id, department, access_level,
                      document_type, project_id, phase_id, state, created_at
               FROM logical_documents WHERE logical_doc_id = ?""",
            (logical_doc_id,),
        ).fetchone()
        if row is None:
            return None
        return LogicalDocument(
            logical_doc_id=row["logical_doc_id"],
            source_identity=row["source_identity"],
            tenant_id=row["tenant_id"],
            department=row["department"],
            access_level=json.loads(row["access_level"]),
            document_type=row["document_type"],
            project_id=row["project_id"],
            phase_id=row["phase_id"],
            state=LogicalDocumentState(row["state"]),
            created_at=self._parse_ts(row["created_at"]),
        )

    def list_logical_documents(self) -> list[LogicalDocument]:
        rows = self.conn.execute(
            """SELECT logical_doc_id, source_identity, tenant_id, department, access_level,
                      document_type, project_id, phase_id, state, created_at
               FROM logical_documents ORDER BY logical_doc_id"""
        ).fetchall()
        return [
            LogicalDocument(
                logical_doc_id=row["logical_doc_id"],
                source_identity=row["source_identity"],
                tenant_id=row["tenant_id"],
                department=row["department"],
                access_level=json.loads(row["access_level"]),
                document_type=row["document_type"],
                project_id=row["project_id"],
                phase_id=row["phase_id"],
                state=LogicalDocumentState(row["state"]),
                created_at=self._parse_ts(row["created_at"]),
            )
            for row in rows
        ]

    def create_version(
        self, logical_doc_id: str, content_hash: str, filename: str, num_pages: int = 0,
        max_retries: int = 5,
    ) -> DocumentVersion:
        """Atomic version allocation (02.1 §2.2). BEGIN IMMEDIATE takes a write lock for
        the duration of the transaction; the UNIQUE(logical_doc_id, version_no) constraint
        plus retry-on-conflict is defense in depth if that lock is ever bypassed."""
        last_error: sqlite3.IntegrityError | None = None
        for _ in range(max_retries):
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT COALESCE(MAX(version_no), 0) AS m FROM document_versions WHERE logical_doc_id = ?",
                    (logical_doc_id,),
                ).fetchone()
                version_no = row["m"] + 1
                version_id = str(uuid.uuid4())
                self.conn.execute(
                    """INSERT INTO document_versions
                       (version_id, logical_doc_id, version_no, content_hash, filename,
                        num_pages, is_active, processing_state, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (
                        version_id, logical_doc_id, version_no, content_hash, filename,
                        num_pages, ProcessingState.QUEUED.value,
                    ),
                )
                self.conn.commit()
                return DocumentVersion(
                    version_id=version_id, logical_doc_id=logical_doc_id, version_no=version_no,
                    content_hash=content_hash, filename=filename, num_pages=num_pages,
                )
            except sqlite3.IntegrityError as e:
                self.conn.rollback()
                last_error = e
                continue
        raise RuntimeError(
            f"could not allocate version_no for {logical_doc_id} after {max_retries} retries"
        ) from last_error

    def activate_version(self, version_id: str) -> None:
        row = self.conn.execute(
            "SELECT logical_doc_id FROM document_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown version_id: {version_id}")
        logical_doc_id = row["logical_doc_id"]
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "UPDATE document_versions SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE logical_doc_id = ?",
            (logical_doc_id,),
        )
        self.conn.execute(
            "UPDATE document_versions SET is_active = 1, processing_state = ?, updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
            (ProcessingState.ACTIVE.value, version_id),
        )
        self.conn.commit()

    def get_versions(self, logical_doc_id: str) -> list[DocumentVersion]:
        rows = self.conn.execute(
            """SELECT version_id, logical_doc_id, version_no, content_hash, filename,
                      num_pages, is_active, processing_state, created_at, updated_at
               FROM document_versions WHERE logical_doc_id = ? ORDER BY version_no""",
            (logical_doc_id,),
        ).fetchall()
        return [
            DocumentVersion(
                version_id=r["version_id"], logical_doc_id=r["logical_doc_id"],
                version_no=r["version_no"], content_hash=r["content_hash"],
                filename=r["filename"], num_pages=r["num_pages"],
                is_active=bool(r["is_active"]),
                processing_state=ProcessingState(r["processing_state"]),
                created_at=self._parse_ts(r["created_at"]),
                updated_at=self._parse_ts(r["updated_at"]),
            )
            for r in rows
        ]

    def set_processing_state(self, version_id: str, state: ProcessingState) -> None:
        self.conn.execute(
            "UPDATE document_versions SET processing_state = ?, updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
            (state.value, version_id),
        )

    def update_version_pages(self, version_id: str, num_pages: int) -> None:
        self.conn.execute(
            "UPDATE document_versions SET num_pages = ?, updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
            (num_pages, version_id),
        )

    def get_project_name(self, project_id: str | None) -> str | None:
        if not project_id:
            return None
        row = self.conn.execute(
            "SELECT name FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return row["name"] if row else None

    def get_phase_name(self, phase_id: str | None) -> str | None:
        if not phase_id:
            return None
        row = self.conn.execute(
            "SELECT name FROM phases WHERE phase_id = ?",
            (phase_id,),
        ).fetchone()
        return row["name"] if row else None

    @staticmethod
    def _parse_ts(value: str | None):
        from datetime import datetime, timezone

        if not value:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row[1] == column for row in rows):
            return
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
