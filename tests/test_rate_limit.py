from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rag.api.main import create_app
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.rate_limit import user_or_ip_key
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base, get_db
from rag.storage.sql.models import User


def test_user_or_ip_key_extracts_user_id_from_a_valid_token():
    request = MagicMock()
    request.headers = {"Authorization": "Bearer valid-token"}

    with patch("rag.crosscutting.security.rate_limit.decode_token") as mock_decode:
        mock_decode.return_value = {"sub": "user-abc-123", "type": "access"}
        key = user_or_ip_key(request)

    assert key == "user:user-abc-123"


def test_user_or_ip_key_falls_back_to_ip_when_no_token():
    request = MagicMock()
    request.headers = {}
    request.client.host = "203.0.113.5"

    key = user_or_ip_key(request)

    assert key == "ip:203.0.113.5"


def test_user_or_ip_key_falls_back_to_ip_on_invalid_token():
    request = MagicMock()
    request.headers = {"Authorization": "Bearer garbage-token"}
    request.client.host = "203.0.113.5"

    with patch("rag.crosscutting.security.rate_limit.decode_token", side_effect=Exception("bad token")):
        key = user_or_ip_key(request)

    assert key == "ip:203.0.113.5"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from rag.config import settings
    monkeypatch.setattr(settings, "audit_log_dir", str(tmp_path))

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)
    shared_session = TestSessionLocal()

    def override_get_db():
        yield shared_session

    owner = User(username="alice", password_hash=hash_password("alice-pass-12345"))
    shared_session.add(owner)
    shared_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app, raise_server_exceptions=False)
    shared_session.close()
    engine.dispose()


def _login(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture()
def auth_headers(client):
    token = _login(client, "alice", "alice-pass-12345")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def active_conversation_id(client, auth_headers):
    resp = client.post("/api/v1/conversations", headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


@patch("rag.api.routers.conversations.build_query_graph")
def test_chat_endpoint_returns_429_after_the_limit_is_exceeded(
    mock_build_graph, client, auth_headers, active_conversation_id,
):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "answer": "mock answer", "citations": [], "standalone_question": "hello",
    }
    mock_build_graph.return_value = mock_graph

    for _ in range(10):
        resp = client.post(
            f"/api/v1/conversations/{active_conversation_id}/messages",
            headers=auth_headers, json={"question": "hello"},
        )
        assert resp.status_code != 429

    resp = client.post(
        f"/api/v1/conversations/{active_conversation_id}/messages",
        headers=auth_headers, json={"question": "hello"},
    )
    assert resp.status_code == 429
