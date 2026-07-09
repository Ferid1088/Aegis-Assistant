"""Waits for the shared `postgres` compose service to actually accept connections.

`docker compose up -d` returns as soon as containers are created and started --
not once Postgres has finished its (several-second, first-run-only) initdb
bootstrap. On a genuinely fresh volume (a brand new CI checkout, or a first
install on a fresh machine -- exactly what install.py is for), the official
postgres image restarts itself once mid-bootstrap before it is ready to accept
connections, so anything that execs into it immediately after `up -d` races
that restart and fails with a connection error. `ensure_glitchtip_database()`
and `alembic upgrade head` both assume postgres is already reachable, so this
must run after `docker compose up -d` and before either of them.
"""

import subprocess
import time


def wait_for_postgres_ready(timeout_s: float = 60.0, interval_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres", "pg_isready", "-U", "postgres"],
                check=True, capture_output=True,
            )
            return
        except subprocess.CalledProcessError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval_s)
