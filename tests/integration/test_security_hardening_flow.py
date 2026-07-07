"""Requires a running Docker daemon and the hardened stack's network-facing pieces
(docker compose up -d nginx neo4j -- pulls in app/postgres/redis via depends_on).
Run with: uv run pytest tests/integration/test_security_hardening_flow.py -v -s
"""
import socket
import subprocess

import httpx
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _port_is_closed(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect((host, port))
        return False
    except Exception:
        return True
    finally:
        sock.close()


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_https_serves_the_app_with_security_headers():
    resp = httpx.get("https://localhost/healthz", verify=False, timeout=5)
    assert resp.status_code == 200
    header_names = {k.lower() for k in resp.headers}
    assert "strict-transport-security" in header_names
    assert "content-security-policy" in header_names


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_http_redirects_to_https():
    resp = httpx.get("http://localhost/healthz", follow_redirects=False, timeout=5)
    assert resp.status_code in (301, 308)
    assert resp.headers["location"].startswith("https://")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_database_ports_are_not_publicly_exposed():
    # postgres (Phase 8.10a/8.10b) and redis (Phase 8.10b's Redis-mandatory
    # fix) are intentionally loopback-published -- install.py's own host-side
    # healthcheck/migration steps need to reach them, and 127.0.0.1-only is
    # not a public exposure (same posture as qdrant's existing loopback port).
    # neo4j has no host-side caller needing it and stays fully unpublished.
    assert not _port_is_closed("localhost", 5432)  # postgres, loopback-only
    assert not _port_is_closed("localhost", 6379)  # redis, loopback-only
    assert _port_is_closed("localhost", 7687)  # neo4j (bolt) -- still fully unpublished


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_app_container_runs_as_non_root():
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "app", "whoami"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "appuser"
