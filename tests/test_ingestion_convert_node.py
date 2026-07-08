import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from rag import config
from rag.graphs import ingestion as ingestion_module
from rag.infra.stores.document_store import SQLiteDocumentStore


def _reset_doc_store(monkeypatch, tmp_path):
    """convert() reads a module-level singleton (_get_doc_store); point it at a
    fresh temp SQLite file and clear the cached instance so this test doesn't
    leak into others."""
    db_path = tmp_path / "docs.db"
    monkeypatch.setattr(config.settings, "sqlite_path", str(db_path))
    monkeypatch.setattr(ingestion_module, "_doc_store", None)
    return db_path


def test_convert_sets_metadata_on_newly_created_logical_document(tmp_path, monkeypatch):
    db_path = _reset_doc_store(monkeypatch, tmp_path)
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    fake_doc = SimpleNamespace(pages={1: object()})
    with patch.object(ingestion_module, "convert_pdf", return_value=(str(tmp_path / "out.json"), None)), \
         patch.object(ingestion_module.DoclingDocument, "load_from_json", return_value=fake_doc):
        result = ingestion_module.convert({
            "file_path": str(pdf_path),
            "department": "Finance",
            "document_type": "invoice",
            "access_level": ["FIN_L1"],
        })

    assert result["status"] == "converted"
    store = SQLiteDocumentStore(str(db_path))
    doc = store.get_logical_document(result["doc_meta"].logical_doc_id)
    assert doc.department == "Finance"
    assert doc.document_type == "invoice"
    assert doc.access_level == ["FIN_L1"]
    store.conn.close()
