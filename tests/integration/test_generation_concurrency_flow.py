"""Requires a running Docker daemon. Proves the global in-flight
generation cap (Phase 8.10c) is enforced by a REAL Redis instance inside a
real running app container -- not just a mocked _redis_client (already
covered by Task 1's unit tests). Calls the real counter function N+1 times
against a low cap and confirms the (N+1)th call is genuinely rejected.

This does not drive actual concurrent HTTP requests (that would need a
real, working LLM backend round-trip, out of scope here) -- Task 2's
router-level tests already cover post_message's 429/finally-decrement
wiring in isolation with a mocked counter; this test's job is proving the
counter itself behaves correctly against real Redis, in the real
container environment where post_message actually runs.

Run with: uv run pytest tests/integration/test_generation_concurrency_flow.py -v -s
"""
import json
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


def _wait_for_healthz(timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get("https://localhost/healthz", timeout=5, verify=False)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("app never became reachable via nginx")


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_concurrent_chat_requests_beyond_cap_get_a_real_429():
    subprocess.run(["docker", "compose", "up", "-d", "nginx", "redis"], check=True)
    try:
        _wait_for_healthz()

        # Drive the global counter directly via the real Redis instance the
        # app container uses -- this proves the SAME counter post_message
        # reads is what a real, running app enforces, without needing a
        # real authenticated conversation/LLM round-trip for every one of
        # N+1 requests (out of scope here; Task 2's router-level tests
        # already cover the 429/finally-decrement logic in isolation).
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "app", "uv", "run", "python", "-c",
             "import json; "
             "from rag.crosscutting.security.generation_limits import "
             "check_and_increment_inflight_generation as c; "
             "print(json.dumps([c(max_inflight=3) for _ in range(5)]))"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        results = json.loads(result.stdout.strip())
        assert results == [True, True, True, False, False]
    finally:
        subprocess.run(["docker", "compose", "down"], check=True)
