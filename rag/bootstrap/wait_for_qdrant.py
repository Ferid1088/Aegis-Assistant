"""Waits for the `qdrant` compose service to actually accept HTTP requests after
`docker compose start qdrant` (or `up -d`) returns.

Mirrors wait_for_postgres_ready/wait_for_neo4j_ready: `docker compose
start`/`up -d` both return as soon as the container process has launched, not
once Qdrant has finished booting and started serving its REST API -- anything
that touches Qdrant immediately afterward (e.g. backup/capture.py's
copy_qdrant stopping/restarting the server around a file copy) races that boot
time. Polls the same `GET /collections` endpoint already used for readiness in
tests/integration/test_qdrant_server_mode.py and
tests/integration/test_migrate_qdrant_to_server.py.
"""

import time

import httpx

from rag.config import settings


def wait_for_qdrant_ready(timeout_s: float = 60.0, interval_s: float = 1.0) -> None:
    url = f"{settings.qdrant_url}/collections"
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2)
            if response.status_code == 200:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(interval_s)

    raise TimeoutError(f"Qdrant did not become ready within {timeout_s}s") from last_exc
