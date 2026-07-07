"""Requires a running Docker daemon. Proves Redis-mandatory enforcement
(Phase 8.10b): stopping the redis container flips /readyz to 503 and makes
check_redis() raise for real, while an in-flight cache call still degrades
softly (rag/capabilities/cache.py is unchanged) instead of raising.

Run with: uv run pytest tests/integration/test_redis_mandatory_flow.py -v -s
"""
import subprocess
import time

import httpx
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _wait_for_readyz(expected_status: int, timeout_s: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get("https://localhost/readyz", timeout=5, verify=False)
            last = r
            if r.status_code == expected_status:
                return r.json()
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError(f"/readyz never reached {expected_status}; last response: {last}")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_readyz_and_check_redis_detect_a_post_startup_redis_outage():
    subprocess.run(["docker", "compose", "up", "-d", "nginx", "redis"], check=True)
    try:
        # Seed get_redis()'s module-level cache with a live, successful
        # connection first -- this is the scenario the .ping() fix (Step 3)
        # exists for: a cached-but-now-dead client, not merely "never configured".
        _wait_for_readyz(200)

        subprocess.run(["docker", "compose", "stop", "redis"], check=True)
        try:
            body = _wait_for_readyz(503)
            assert "redis" in body["reason"].lower() or "unavailable" in body["reason"].lower()

            # Bare `python` on PATH inside the app container is the system
            # interpreter, not the uv-managed venv (see Dockerfile: only `uv
            # run` prepends .venv/bin) -- confirmed for real: it raises
            # ModuleNotFoundError on `pydantic_settings`. `uv run python`
            # matches the invocation pattern already used successfully by
            # tests/integration/test_pgbouncer_pooling.py.
            check_redis_result = subprocess.run(
                ["docker", "compose", "exec", "-T", "app", "uv", "run", "python", "-c",
                 "from rag.healthcheck import check_redis; check_redis()"],
                capture_output=True, text=True,
            )
            assert check_redis_result.returncode != 0

            # rag/capabilities/cache.py's runtime behavior is unchanged: a
            # real, live cached() call inside the same now-Redis-less app
            # container must still degrade to calling fn() directly, not raise.
            soft_degrade_result = subprocess.run(
                ["docker", "compose", "exec", "-T", "app", "uv", "run", "python", "-c",
                 "from rag.capabilities.cache import cached; "
                 "print(cached('test_redis_mandatory', 'key', 60, lambda: 'computed-value'))"],
                capture_output=True, text=True,
            )
            assert soft_degrade_result.returncode == 0, soft_degrade_result.stderr
            assert "computed-value" in soft_degrade_result.stdout
        finally:
            subprocess.run(["docker", "compose", "start", "redis"], check=True)
            _wait_for_readyz(200)
    finally:
        pass
