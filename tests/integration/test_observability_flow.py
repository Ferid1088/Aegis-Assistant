"""Requires a running Docker daemon and the full stack (docker compose up -d
app worker postgres redis -- GlitchTip is checked separately below, given the
acknowledged uncertainty in Task 6).
Run with: uv run pytest tests/integration/test_observability_flow.py -v -s
"""
import subprocess

import httpx
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_healthz_and_readyz_respond_on_the_real_app():
    resp = httpx.get("http://localhost:8000/healthz", timeout=5)
    assert resp.status_code == 200

    resp = httpx.get("http://localhost:8000/readyz", timeout=5)
    assert resp.status_code == 200


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_metrics_endpoint_is_scrapable_on_the_real_app():
    resp = httpx.get("http://localhost:8000/metrics", timeout=5)
    assert resp.status_code == 200
    assert "http_" in resp.text


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_glitchtip_database_exists():
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-tAc",
         "SELECT 1 FROM pg_database WHERE datname='glitchtip'"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "1"


