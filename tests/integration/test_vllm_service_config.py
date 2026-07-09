"""Requires the `docker` CLI (no containers need to be running): confirms
docker-compose.yml's vllm service (Phase 8.10c) is correctly profile-gated
and its host-vs-container VLLM_BASE_URL split resolves -- by rendering the
real compose config, not just grepping the YAML text.

Run with: uv run pytest tests/integration/test_vllm_service_config.py -v -s
"""
import subprocess

import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_vllm_service_excluded_from_default_compose_up():
    result = subprocess.run(
        ["docker", "compose", "config", "--services"], capture_output=True, text=True, check=True,
    )
    assert "vllm" not in result.stdout.splitlines()


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_vllm_service_included_with_gpu_profile():
    result = subprocess.run(
        ["docker", "compose", "--profile", "gpu", "config", "--services"],
        capture_output=True, text=True, check=True,
    )
    assert "vllm" in result.stdout.splitlines()


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_app_and_worker_vllm_base_url_points_at_vllm_container():
    result = subprocess.run(
        ["docker", "compose", "--profile", "gpu", "config"], capture_output=True, text=True, check=True,
    )
    assert result.stdout.count("VLLM_BASE_URL: http://vllm:8000/v1") == 2  # app, worker
