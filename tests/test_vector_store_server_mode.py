"""Tests that QdrantVectorStore picks server mode vs embedded mode based on
settings.qdrant_url, per Phase 8.10a."""

from unittest.mock import patch

from rag.config import settings
from rag.storage.vector_store import QdrantVectorStore


def test_uses_server_mode_when_qdrant_url_set(monkeypatch):
    monkeypatch.setattr(settings, "qdrant_url", "http://localhost:6333")
    with patch("rag.storage.vector_store.QdrantClient") as mock_client_cls:
        QdrantVectorStore()
        mock_client_cls.assert_called_once_with(url="http://localhost:6333")


def test_uses_embedded_mode_when_qdrant_url_empty(monkeypatch):
    monkeypatch.setattr(settings, "qdrant_url", "")
    monkeypatch.setattr(settings, "qdrant_path", "./data/qdrant")
    with patch("rag.storage.vector_store.QdrantClient") as mock_client_cls:
        QdrantVectorStore()
        mock_client_cls.assert_called_once_with(path="./data/qdrant")
