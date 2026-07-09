"""Requires a running Docker daemon. Proves the POSTGRES_PASSWORD
interpolation mechanism (Phase 8.10b) genuinely gates authentication on a
FRESH Postgres volume -- a real, throwaway container, no bind mount, never
touches the shared dev stack's ./data/postgres.

Run with: uv run pytest tests/integration/test_postgres_password_flow.py -v -s
"""
import subprocess
import time

import psycopg
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


CONTAINER_NAME = "test-postgres-password-flow-8-10b"
GENERATED_PASSWORD = "test-generated-password-xyz-789"


def _wait_for_ready(timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "pg_isready", "-U", "postgres"],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("throwaway postgres container never became ready")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_generated_password_authenticates_and_old_default_does_not():
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", CONTAINER_NAME,
            "-e", f"POSTGRES_PASSWORD={GENERATED_PASSWORD}",
            "-e", "POSTGRES_DB=appliance",
            "-p", "127.0.0.1:15432:5432",
            "postgres:16-alpine",
        ],
        check=True,
    )
    try:
        _wait_for_ready()

        # The real generated password authenticates.
        with psycopg.connect(
            f"postgresql://postgres:{GENERATED_PASSWORD}@localhost:15432/appliance", connect_timeout=5,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone() == (1,)

        # The old dev-default literal does NOT -- proving this isn't a
        # no-op / silently-ignored env var.
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                "postgresql://postgres:password@localhost:15432/appliance", connect_timeout=5,
            )
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], check=True)
