"""Ensures the 'glitchtip' Postgres database exists in the shared postgres
container, idempotently -- a repeated install.py run must not error on
'database already exists'.
"""

import subprocess
import time


def ensure_glitchtip_database(max_attempts: int = 5, retry_delay: float = 2.0) -> None:
    """Retries the whole check-then-create sequence on failure.

    Even after `wait_for_postgres_ready()`, a genuinely fresh Postgres container
    briefly reports ready during the official image's own initdb bootstrap, then
    shuts itself down and restarts for real (a standard part of that image's
    first-run behavior) -- a command dispatched into that narrow window gets its
    connection killed mid-statement ("terminating connection due to
    administrator command"). Retrying survives that race: whichever attempt
    lands on the durable, fully-started server succeeds, and the check-then-
    create logic below is naturally idempotent across attempts.
    """
    last_exc: subprocess.CalledProcessError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            check = subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-tAc",
                 "SELECT 1 FROM pg_database WHERE datname='glitchtip'"],
                capture_output=True, text=True, check=True,
            )
            if check.stdout.strip() != "1":
                subprocess.run(
                    ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-c",
                     "CREATE DATABASE glitchtip"],
                    check=True,
                )
            return
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(retry_delay)

    raise last_exc
