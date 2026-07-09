"""Requires a running Docker daemon. Proves Phase 8.10d's nginx dynamic
upstream actually load-balances across scaled `app` replicas, and that
scaled `worker` replicas are independently visible to Celery.
"""

import subprocess
import socket
import time

import httpx
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_healthz(timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get("https://localhost/healthz", timeout=5, verify=False)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("app never became reachable via nginx")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_scaled_app_replicas_are_individually_reachable():
    required_ports = [5432, 6333, 6379, 80, 443]
    busy = [port for port in required_ports if not _port_available(port)]
    if busy:
        pytest.skip(f"required compose ports already in use locally: {busy}")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--scale", "app=2", "nginx", "redis", "postgres", "pgbouncer", "qdrant"],
        check=True,
    )
    try:
        _wait_for_healthz()
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", "app"], capture_output=True, text=True, check=True,
        )
        container_ids = [c for c in result.stdout.strip().splitlines() if c]
        assert len(container_ids) == 2, f"expected 2 app replicas, found {len(container_ids)}"
        for container_id in container_ids:
            status = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            assert status == "healthy", f"replica {container_id} is {status}, not healthy"
    finally:
        subprocess.run(["docker", "compose", "down"], check=True)


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_scaled_workers_are_independently_visible_to_celery():
    required_ports = [5432, 6333, 6379]
    busy = [port for port in required_ports if not _port_available(port)]
    if busy:
        pytest.skip(f"required compose ports already in use locally: {busy}")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--scale", "worker=2", "worker", "redis", "postgres", "pgbouncer", "qdrant"],
        check=True,
    )
    try:
        deadline = time.monotonic() + 60.0
        hostnames = set()
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "compose", "exec", "-T", "worker", "uv", "run", "celery",
                 "-A", "rag.worker.celery_app", "inspect", "ping"],
                capture_output=True, text=True,
            )
            hostnames = {
                line.split("->")[1].split(":")[0].strip()
                for line in result.stdout.splitlines() if "->" in line
            }
            if len(hostnames) == 2:
                break
            time.sleep(2)
        assert len(hostnames) == 2, f"expected 2 distinct worker hostnames, found: {hostnames}"
    finally:
        subprocess.run(["docker", "compose", "down"], check=True)