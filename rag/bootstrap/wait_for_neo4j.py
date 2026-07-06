"""Waits for Neo4j to actually accept Bolt connections after `docker compose start
neo4j` (or `up -d`) returns.

Unlike Postgres, Neo4j is a JVM application and can take considerably longer
(often 10-30+ seconds, sometimes more under load) to finish booting and start
accepting Bolt connections after its container is (re)started. `docker compose
start`/`up -d` both return as soon as the container process has been launched,
not once the application inside it is actually ready -- anything that connects
immediately afterward (e.g. backup.py's dump_neo4j stopping/restarting Neo4j
around a file copy, or restore.py doing the same) races that boot time and gets
connection-refused errors.
"""

import time


def wait_for_neo4j_ready(timeout_s: float = 60.0, interval_s: float = 1.0) -> None:
    from rag.storage.graph_store import Neo4jGraphStore

    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            store = Neo4jGraphStore()
            store.close()
            return
        except Exception as exc:
            last_exc = exc
            time.sleep(interval_s)

    raise TimeoutError(f"Neo4j did not become ready within {timeout_s}s") from last_exc
