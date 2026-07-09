import os
import tempfile
import threading

from rag.domain.document_lifecycle import LogicalDocument, ProcessingState
from rag.infra.stores.document_store import SQLiteDocumentStore


def _store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    return SQLiteDocumentStore(db_path), db_path


def test_find_logical_by_identity_none_when_absent():
    store, db_path = _store()
    try:
        assert store.find_logical_by_identity("filesystem:/x.pdf") is None
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_find_logical_by_content_hash_none_when_absent():
    store, db_path = _store()
    try:
        assert store.find_logical_by_content_hash("deadbeef") is None
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_find_logical_by_content_hash_after_create_version():
    store, db_path = _store()
    try:
        doc = LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf")
        store.create_logical_document(doc)
        store.create_version(logical_doc_id="L1", content_hash="deadbeef", filename="x.pdf")
        assert store.find_logical_by_content_hash("deadbeef") == "L1"
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_create_and_find_logical_document():
    store, db_path = _store()
    try:
        doc = LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf")
        store.create_logical_document(doc)
        assert store.find_logical_by_identity("filesystem:/x.pdf") == "L1"
        fetched = store.get_logical_document("L1")
        assert fetched is not None
        assert fetched.source_identity == "filesystem:/x.pdf"
        assert fetched.tenant_id == "default"
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_create_version_starts_at_one():
    store, db_path = _store()
    try:
        store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf"))
        v = store.create_version(logical_doc_id="L1", content_hash="h1", filename="x.pdf", num_pages=3)
        assert v.version_no == 1
        assert v.processing_state == ProcessingState.QUEUED
        assert v.is_active
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_create_version_increments_under_same_logical_doc():
    store, db_path = _store()
    try:
        store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf"))
        v1 = store.create_version(logical_doc_id="L1", content_hash="h1", filename="x.pdf")
        v2 = store.create_version(logical_doc_id="L1", content_hash="h2", filename="x.pdf")
        assert v1.version_no == 1
        assert v2.version_no == 2
        assert v1.version_id != v2.version_id
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_concurrent_create_version_never_duplicates_version_no():
    store, db_path = _store()
    store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf"))
    store.conn.close()

    results: list[int] = []
    errors: list[Exception] = []

    def worker(content_hash: str) -> None:
        try:
            s = SQLiteDocumentStore(db_path)
            v = s.create_version(logical_doc_id="L1", content_hash=content_hash, filename="x.pdf")
            results.append(v.version_no)
            s.conn.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f"h{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors, f"unexpected errors: {errors}"
        assert sorted(results) == [1, 2], f"expected exactly one v1 and one v2, got {results}"
    finally:
        os.unlink(db_path)


def test_activate_version_deactivates_siblings():
    store, db_path = _store()
    try:
        store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf"))
        v1 = store.create_version(logical_doc_id="L1", content_hash="h1", filename="x.pdf")
        v2 = store.create_version(logical_doc_id="L1", content_hash="h2", filename="x.pdf")

        store.activate_version(v2.version_id)

        versions = {v.version_id: v for v in store.get_versions("L1")}
        assert not versions[v1.version_id].is_active
        assert versions[v2.version_id].is_active
        assert versions[v2.version_id].processing_state == ProcessingState.ACTIVE
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_get_versions_ordered_by_version_no():
    store, db_path = _store()
    try:
        store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf"))
        store.create_version(logical_doc_id="L1", content_hash="h1", filename="x.pdf")
        store.create_version(logical_doc_id="L1", content_hash="h2", filename="x.pdf")
        store.create_version(logical_doc_id="L1", content_hash="h3", filename="x.pdf")
        versions = store.get_versions("L1")
        assert [v.version_no for v in versions] == [1, 2, 3]
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_set_processing_state():
    store, db_path = _store()
    try:
        store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf"))
        v = store.create_version(logical_doc_id="L1", content_hash="h1", filename="x.pdf")
        store.set_processing_state(v.version_id, ProcessingState.CONVERTING)
        versions = store.get_versions("L1")
        assert versions[0].processing_state == ProcessingState.CONVERTING
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_existing_register_exists_mark_superseded_unaffected():
    """Backward compatibility: the original 02 flow must still work unchanged."""
    from rag.domain.models import DocumentMeta

    store, db_path = _store()
    try:
        meta = DocumentMeta(doc_id="d1", filename="f.pdf", content_hash="hash1", num_pages=5)
        assert store.register(meta) is True
        assert store.exists("hash1") is True
        assert store.register(meta) is False  # exists() short-circuits, per existing behavior
        meta2 = DocumentMeta(doc_id="d2", filename="f.pdf", content_hash="hash2", num_pages=5)
        store.register(meta2)
        store.mark_superseded("d1", "d2")
        row = store.conn.execute("SELECT is_current, superseded_by FROM documents WHERE doc_id = 'd1'").fetchone()
        assert row["is_current"] == 0
        assert row["superseded_by"] == "d2"
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_list_logical_documents_returns_all(tmp_path):
    store, db_path = _store()
    try:
        store.create_logical_document(LogicalDocument(logical_doc_id="d1", source_identity="filesystem:/a.pdf"))
        store.create_logical_document(LogicalDocument(logical_doc_id="d2", source_identity="filesystem:/b.pdf"))

        docs = store.list_logical_documents()
        assert {d.logical_doc_id for d in docs} == {"d1", "d2"}
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_list_logical_documents_empty(tmp_path):
    store, db_path = _store()
    try:
        assert store.list_logical_documents() == []
    finally:
        store.conn.close()
        os.unlink(db_path)


def test_create_and_get_logical_document_with_title():
    store, db_path = _store()
    try:
        doc = LogicalDocument(logical_doc_id="L1", source_identity="filesystem:/x.pdf", title="Employee Handbook")
        store.create_logical_document(doc)
        fetched = store.get_logical_document("L1")
        assert fetched is not None
        assert fetched.title == "Employee Handbook"
    finally:
        store.conn.close()
        os.unlink(db_path)
