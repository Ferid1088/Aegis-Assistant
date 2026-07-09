"""Requires the `docker` CLI (no containers need to be running): confirms
docker-compose.yml's ${POSTGRES_PASSWORD:-password} interpolation (Phase
8.10b) is genuinely wired to every consumer, by rendering the real compose
config with a controlled override -- not just grepping the YAML text.

Run with: uv run pytest tests/integration/test_docker_compose_config.py -v -s
"""
import os
import subprocess

import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_compose_config_renders_generated_postgres_password_everywhere():
    env = {**os.environ, "POSTGRES_PASSWORD": "test-generated-secret-123"}
    result = subprocess.run(
        ["docker", "compose", "config"], capture_output=True, text=True, check=True, env=env,
    )
    rendered = result.stdout
    # postgres, pgbouncer, app, worker, glitchtip-migrate, glitchtip-web,
    # glitchtip-worker (Task 3 adds pgbouncer to this list).
    assert rendered.count("test-generated-secret-123") >= 7


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_compose_config_falls_back_to_dev_default_password_when_unset():
    env = {k: v for k, v in os.environ.items() if k != "POSTGRES_PASSWORD"}
    result = subprocess.run(
        ["docker", "compose", "config"], capture_output=True, text=True, check=True, env=env,
    )
    assert "postgres:password@postgres:5432/appliance" in result.stdout
    assert result.stdout.count("postgres:password@postgres:5432/glitchtip") == 3


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_compose_config_points_app_and_worker_database_url_at_pgbouncer():
    result = subprocess.run(
        ["docker", "compose", "config"], capture_output=True, text=True, check=True,
    )
    assert result.stdout.count("@pgbouncer:5432/appliance") == 2  # app, worker
