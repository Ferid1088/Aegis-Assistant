"""Requires a running Docker daemon. Proves the healthchecks added in
Phase 8.10d genuinely make each of these 8 services report healthy in real
Docker. Excludes vllm (GPU-hardware-dependent, unverifiable here) and the
tooling services that intentionally got no healthcheck.
"""

import subprocess
import socket
import time

import pytest

SERVICES_WITH_HEALTHCHECKS = [
    "postgres", "redis", "pgbouncer", "neo4j", "qdrant", "app", "worker", "nginx",
]


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


def _container_name(service: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "ps", "-q", service], capture_output=True, text=True, check=True,
    )
    container_id = result.stdout.strip()
    assert container_id, f"no running container found for service {service!r}"
    return container_id


def _wait_for_healthy(service: str, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_status = None
    while time.monotonic() < deadline:
        container_id = _container_name(service)
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
            capture_output=True, text=True, check=True,
        )
        last_status = result.stdout.strip()
        if last_status == "healthy":
            return
        time.sleep(2)
    raise AssertionError(f"{service} never became healthy; last status: {last_status!r}")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_all_core_services_report_healthy():
    required_ports = [5432, 6333, 6379, 80, 443]
    busy = [port for port in required_ports if not _port_available(port)]
    if busy:
        pytest.skip(f"required compose ports already in use locally: {busy}")
    subprocess.run(["docker", "compose", "up", "-d"] + SERVICES_WITH_HEALTHCHECKS, check=True)
    try:
        for service in SERVICES_WITH_HEALTHCHECKS:
            _wait_for_healthy(service)
    finally:
        subprocess.run(["docker", "compose", "down"], check=True)