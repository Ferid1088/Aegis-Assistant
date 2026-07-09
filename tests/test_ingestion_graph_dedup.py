import os
import tempfile
from unittest.mock import MagicMock, patch

import rag.graphs.ingestion as ingestion
from rag.domain.document_lifecycle import LogicalDocument
from rag.infra.stores.document_store import SQLiteDocumentStore


def _store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    return SQLiteDocumentStore(db_path), db_path


def _seed_existing_document(store, *, content_hash: str, department: str) -> str:
    logical_doc_id = "existing-doc"
    store.create_logical_document(
        LogicalDocument(logical_doc_id=logical_doc_id, source_identity="filesystem:/seed.pdf", department=department)
    )
    store.create_version(logical_doc_id=logical_doc_id, content_hash=content_hash, filename="seed.pdf")
    return logical_doc_id


def test_convert_skips_as_duplicate_when_same_department_already_has_this_content(tmp_path, monkeypatch):
    store, db_path = _store()
    try:
        file_path = tmp_path / "upload.pdf"
        file_path.write_bytes(b"same bytes")
        real_hash = ingestion._content_hash(file_path)
        existing_logical_doc_id = _seed_existing_document(store, content_hash=real_hash, department="HR")

        monkeypatch.setattr(ingestion, "_doc_store", store)

        result = ingestion.convert({"file_path": str(file_path), "department_id": "HR"})

        assert result["status"] == "skipped (duplicate)"
        assert result["logical_doc_id"] == existing_logical_doc_id
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_convert_ignores_the_dedup_gate_entirely_for_an_explicit_new_version_upload(tmp_path, monkeypatch):
    # An explicit "upload as new version of X" (target_logical_doc_id set) must never be
    # silently discarded just because its bytes happen to match some unrelated document
    # -- the pre-fix code ran the global content-hash gate unconditionally, before even
    # looking at target_logical_doc_id.
    store, db_path = _store()
    try:
        file_path = tmp_path / "upload.pdf"
        file_path.write_bytes(b"same bytes")
        real_hash = ingestion._content_hash(file_path)
        _seed_existing_document(store, content_hash=real_hash, department="HR")

        monkeypatch.setattr(ingestion, "_doc_store", store)

        fake_doc = MagicMock()
        fake_doc.pages = {}
        with patch.object(ingestion, "convert_pdf", return_value=(tmp_path / "doc.json", None)), \
             patch.object(ingestion.DoclingDocument, "load_from_json", return_value=fake_doc):
            result = ingestion.convert({"file_path": str(file_path), "target_logical_doc_id": "existing-doc"})

        assert result.get("status") != "skipped (duplicate)"
        assert result["status"] == "converted"
    finally:
        store.conn.close()
        os.unlink(db_path)
