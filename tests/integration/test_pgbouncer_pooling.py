"""Requires a running Docker daemon. Proves docker-compose.yml's pgbouncer
service (Phase 8.10b) actually pools connections: many concurrent client
connections through pgbouncer must result in far fewer real backend
connections against Postgres, not just "the container starts".

Run with: uv run pytest tests/integration/test_pgbouncer_pooling.py -v -s
"""
import os
import subprocess
import time

import pytest

PROBE_SCRIPT = '''
import os
import threading
import time

import psycopg

N_CLIENTS = 20

raw = os.environ["DATABASE_URL"]  # postgresql+psycopg://postgres:<pw>@pgbouncer:5432/appliance
pool_url = raw.replace("postgresql+psycopg://", "postgresql://")
direct_url = pool_url.replace("@pgbouncer:5432", "@postgres:5432")

def hold_connection():
    with psycopg.connect(pool_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_sleep(2)")

threads = [threading.Thread(target=hold_connection) for _ in range(N_CLIENTS)]
for t in threads:
    t.start()
time.sleep(1)  # let all N_CLIENTS threads reach pg_sleep before counting

with psycopg.connect(direct_url, connect_timeout=5) as admin_conn:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            ("appliance",),
        )
        peak_backend_connections = cur.fetchone()[0]

for t in threads:
    t.join()

print(f"PEAK_BACKEND_CONNECTIONS={peak_backend_connections}")
print(f"N_CLIENTS={N_CLIENTS}")
'''


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _wait_for_exec_ready(service: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", service, "python", "-c", "print('ready')"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"{service} never became exec-ready")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_pgbouncer_pools_connections_below_client_count(tmp_path):
    env_override = {**os.environ, "PGBOUNCER_POOL_SIZE": "5"}
    subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate", "pgbouncer"],
        check=True, env=env_override,
    )
    # `app` depends_on pgbouncer, so `up -d ... app` reconciles pgbouncer's
    # config too -- confirmed for real: omitting PGBOUNCER_POOL_SIZE here
    # silently recreates pgbouncer back onto the *default* pool size (20),
    # defeating the whole test (observed peak == 20, i.e. no capping at all).
    # Must carry the same env_override through every `up` call that touches
    # a service depending on pgbouncer.
    subprocess.run(["docker", "compose", "up", "-d", "postgres", "app"], check=True, env=env_override)
    try:
        _wait_for_exec_ready("app")

        probe_path = tmp_path / "pgbouncer_probe.py"
        probe_path.write_text(PROBE_SCRIPT)
        # `docker compose cp` refuses to write into a tmpfs mount when the
        # container has read_only: true (confirmed for real: "container rootfs
        # is marked read-only", even though the same tmpfs path is writable via
        # `docker compose exec`) -- stage into the bind-mounted ./data volume
        # instead, which `docker cp` can write to under read_only: true.
        try:
            subprocess.run(
                ["docker", "compose", "cp", str(probe_path), "app:/app/data/pgbouncer_probe.py"],
                check=True,
            )
            # Bare `python` on PATH is the system interpreter (/usr/local/bin/python,
            # no site-packages) -- confirmed for real: `import psycopg` fails there.
            # Project deps (incl. psycopg) live in the uv-managed venv, reached via
            # `uv run python` (same as the app/worker services' own commands).
            result = subprocess.run(
                ["docker", "compose", "exec", "-T", "app", "uv", "run", "python", "/app/data/pgbouncer_probe.py"],
                capture_output=True, text=True, timeout=60,
            )
        finally:
            subprocess.run(
                ["docker", "compose", "exec", "-T", "app", "rm", "-f", "/app/data/pgbouncer_probe.py"],
                capture_output=True,
            )
        assert result.returncode == 0, result.stderr

        lines = dict(
            line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line
        )
        peak = int(lines["PEAK_BACKEND_CONNECTIONS"])
        n_clients = int(lines["N_CLIENTS"])
        print(f"PEAK_BACKEND_CONNECTIONS={peak} N_CLIENTS={n_clients}")

        assert n_clients == 20
        # With DEFAULT_POOL_SIZE=5, 20 concurrent clients must be multiplexed
        # onto far fewer real backend connections -- proves pooling, not just
        # "connections succeed" (which they'd also do with zero pooling, since
        # Postgres's own default max_connections=100 is nowhere near 20).
        assert peak <= 5, f"expected pgbouncer to cap backend connections at 5, got {peak}"
    finally:
        subprocess.run(["docker", "compose", "up", "-d", "--force-recreate", "pgbouncer"], check=True)
