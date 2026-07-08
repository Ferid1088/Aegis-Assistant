"""Requires a running Docker daemon: brings up the real `qdrant` service and
confirms QdrantVectorStore's server-mode branch (Phase 8.10a) works
identically to embedded mode for the operations the rest of the app uses.

Run with: uv run pytest tests/integration/test_qdrant_server_mode.py -v -s
"""
import subprocess
import time
import uuid

import httpx
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_server_mode_matches_embedded_behavior(monkeypatch, tmp_path):
    subprocess.run(["docker", "compose", "up", "-d", "qdrant"], check=True)

    for _ in range(30):
        try:
            r = httpx.get("http://localhost:6333/collections", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        pytest.fail("qdrant server did not become reachable on 127.0.0.1:6333")

    from rag.config import settings
    from rag.infra.stores.vector_store import QdrantVectorStore
    from rag.domain.models import ChunkRecord

    monkeypatch.setattr(settings, "qdrant_url", "http://localhost:6333")
    monkeypatch.setattr(settings, "qdrant_collection", "test_server_mode_8_10a")

    store = QdrantVectorStore()
    store.ensure_collection(dense_dim=4)

    # NOTE: the brief's example used chunk_id="server-mode-test-1" here, which
    # Qdrant rejects with a 400 ("... is not a valid point ID, valid values are
    # either an unsigned integer or a UUID") -- confirmed for real against the
    # live server container. This is the same repro-script defect already
    # found and worked around in this task's Step 4 (a real Qdrant point-ID
    # constraint that applies identically in embedded and server mode, not a
    # server-mode-specific issue), so it's fixed the same way here: a real
    # UUID, matching the convention used elsewhere in this repo (e.g.
    # tests/test_vector_store_payload.py).
    chunk_id_value = str(uuid.uuid4())
    chunk = ChunkRecord(
        chunk_id=chunk_id_value, type="text", content="hello from server mode",
        source_file="x.pdf", doc_id="d1", page_numbers=[1], heading_path=[], bboxes=[],
    )
    store.upsert([chunk], dense=[[0.1, 0.2, 0.3, 0.4]], sparse=[{"indices": [1], "values": [1.0]}])

    dense_results = store.search_dense([0.1, 0.2, 0.3, 0.4], k=5)
    assert len(dense_results) == 1
    assert dense_results[0].chunk_id == chunk_id_value

    sparse_results = store.search_sparse({"indices": [1], "values": [1.0]}, k=5)
    assert len(sparse_results) == 1
    assert sparse_results[0].chunk_id == chunk_id_value

    store.client.delete_collection("test_server_mode_8_10a")
