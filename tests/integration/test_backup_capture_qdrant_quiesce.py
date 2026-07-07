"""Requires a running Docker daemon: brings up the real `qdrant` service and
proves the Phase 8.10a final-review fix to copy_qdrant() (rag/backup/capture.py)
genuinely quiesces a server-mode Qdrant before copying its bind-mounted storage
directory -- stopping the real container, copying, restarting it, and waiting
for it to accept requests again -- mirroring dump_neo4j's existing stop/copy/
restart pattern in the same module. Also proves the resulting backup is a
faithful, restorable snapshot (not just "a copytree call happened"), by
restoring it into a separate throwaway container on a different port and
reading the data back.

Run with: uv run pytest tests/integration/test_backup_capture_qdrant_quiesce.py -v -s
"""
import subprocess
import time
import uuid

import httpx
import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _wait_http_ready(url: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    pytest.fail(f"{url} did not become reachable within {timeout_s}s")


def _qdrant_container_id() -> str:
    result = subprocess.run(
        ["docker", "compose", "ps", "-q", "qdrant"], check=True, capture_output=True, text=True,
    )
    container_id = result.stdout.strip()
    assert container_id, "expected a running `qdrant` compose container"
    return container_id


def _container_started_at(container_id: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.StartedAt}}", container_id],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_copy_qdrant_quiesces_server_and_produces_restorable_backup(tmp_path, monkeypatch):
    from rag.backup.capture import copy_qdrant
    from rag.config import settings

    subprocess.run(["docker", "compose", "up", "-d", "qdrant"], check=True)
    _wait_http_ready("http://localhost:6333/collections")

    monkeypatch.setattr(settings, "qdrant_url", "http://localhost:6333")

    collection = f"test_capture_quiesce_{uuid.uuid4().hex[:8]}"
    client = QdrantClient(url="http://localhost:6333")
    try:
        client.create_collection(
            collection, vectors_config=qm.VectorParams(size=4, distance=qm.Distance.COSINE),
        )
        client.upsert(
            collection,
            points=[qm.PointStruct(id=1, vector=[0.1, 0.2, 0.3, 0.4], payload={"marker": "quiesce-test"})],
        )

        container_id = _qdrant_container_id()
        started_before = _container_started_at(container_id)

        dest = tmp_path / "qdrant_backup"
        copy_qdrant(dest)

        # -- real evidence the container was genuinely stopped and restarted, not
        # just copied live: State.StartedAt changes only across an actual
        # stop+start cycle, not a no-op. --
        started_after = _container_started_at(container_id)
        assert started_after != started_before

        # -- copy_qdrant's own wait_for_qdrant_ready() call already blocked until
        # this was true, but confirm independently that the server is genuinely
        # back up and serving requests by the time copy_qdrant() returns. --
        r = httpx.get("http://localhost:6333/collections", timeout=2)
        assert r.status_code == 200

        # -- the backed-up directory must contain the collection's on-disk
        # server-format artifacts (not e.g. an empty/partial copy from a torn
        # snapshot) --
        assert (dest / "collections" / collection).exists()

        # -- mutate/delete the live data so restoring the backup is the only way
        # the marker point can still be found afterward --
        client.delete_collection(collection)
    finally:
        client.close()

    # -- restorability: point a separate, throwaway qdrant container (different
    # host port, so it doesn't collide with the real compose-managed service)
    # at the backup directory and confirm the marker point reads back intact. --
    restore_container = f"qdrant-restore-check-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", restore_container,
            "-p", "16333:6333", "-v", f"{dest}:/qdrant/storage", "qdrant/qdrant:latest",
        ],
        check=True, capture_output=True,
    )
    try:
        _wait_http_ready("http://localhost:16333/collections", timeout_s=30.0)
        restore_client = QdrantClient(url="http://localhost:16333")
        try:
            points = restore_client.retrieve(collection, ids=[1])
            assert len(points) == 1
            assert points[0].payload["marker"] == "quiesce-test"
        finally:
            restore_client.close()
    finally:
        subprocess.run(["docker", "stop", restore_container], capture_output=True)
