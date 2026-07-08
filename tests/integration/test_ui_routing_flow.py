"""Requires a running Docker daemon and the hardened stack's network-facing pieces
(docker compose up -d nginx ui app -- pulls in dependencies via depends_on).
Run with: uv run pytest tests/integration/test_ui_routing_flow.py -v -s

Locks in the nginx routing fix from this branch: the catch-all `location /`
now proxies to the `ui` service (Next.js) instead of the FastAPI `app`
service, while six explicit backend-only paths (/api/v1/docs,
/api/v1/openapi.json, /redoc, /metrics, /healthz, /readyz) still go straight
to `app`. Everything else under /api/v1/* now flows through the UI's
server-side proxy route, which requires a session cookie.
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
def test_root_redirects_to_ui_login():
    resp = httpx.get("https://localhost/", verify=False, timeout=5, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/login"


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_backend_only_paths_still_reach_app_directly():
    resp = httpx.get("https://localhost/healthz", verify=False, timeout=5)
    assert resp.status_code == 200


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_generic_api_v1_path_routes_through_ui_proxy():
    resp = httpx.get("https://localhost/api/v1/conversations", verify=False, timeout=5)
    assert resp.status_code == 401
    assert resp.json() == {"code": "unauthorized", "message": "no session"}
