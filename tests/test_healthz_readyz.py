import io
import json
import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag.api.main import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_returns_200(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@patch("rag.api.main.check_redis")
@patch("rag.api.main.check_postgres")
def test_readyz_returns_200_when_postgres_and_redis_healthy(mock_check_postgres, mock_check_redis, client):
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
    mock_check_postgres.assert_called_once()
    mock_check_redis.assert_called_once()


@patch("rag.api.main.check_redis")
@patch("rag.api.main.check_postgres")
def test_readyz_returns_503_when_postgres_unhealthy(mock_check_postgres, mock_check_redis, client):
    mock_check_postgres.side_effect = RuntimeError("connection refused")

    resp = client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["status"] == "not ready"
    assert "connection refused" in resp.json()["reason"]


@patch("rag.api.main.check_redis")
@patch("rag.api.main.check_postgres")
def test_readyz_returns_503_when_redis_unhealthy(mock_check_postgres, mock_check_redis, client):
    mock_check_redis.side_effect = RuntimeError("Redis unavailable")

    resp = client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["status"] == "not ready"
    assert "Redis unavailable" in resp.json()["reason"]


def test_healthz_request_is_logged_with_its_own_correlation_id(client):
    stream = io.StringIO()
    logging.getLogger().handlers[0].stream = stream

    resp = client.get("/healthz")

    request_id = resp.headers["X-Request-ID"]
    log_lines = [json.loads(line) for line in stream.getvalue().strip().splitlines() if line]
    matching = [entry for entry in log_lines if entry.get("request_id") == request_id]
    assert len(matching) >= 1
    assert matching[0]["event"] == "request completed"
