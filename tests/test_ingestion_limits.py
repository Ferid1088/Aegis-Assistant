from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import documents
from rag.crosscutting.security.ingestion_limits import (
    check_and_increment_queued_ingestion, decrement_queued_ingestion,
)
from rag.crosscutting.security.rate_limit import limiter
from rag.crosscutting.security.tokens import create_access_token
from rag.storage.sql.base import get_db
from rag.storage.sql.models import Role, RolePermission, User, UserRole, UserSession


def _make_user_with_token(db_session, username):
    user = User(username=username)
    db_session.add(user)
    db_session.flush()
    session = UserSession(
        user_id=user.id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()
    token = create_access_token(str(user.id), str(session.id), user.token_version)
    return user, token


def _make_user_with_permission(db_session, username, permission):
    user, token = _make_user_with_token(db_session, username)
    role = Role(name=f"role-{permission}-{username}")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=permission))
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user, token


@pytest.fixture()
def client(db_session, tmp_path, monkeypatch):
    from rag import config
    monkeypatch.setattr(config.settings, "upload_dir", str(tmp_path / "uploads"))

    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(documents.router, prefix="/api/v1/documents")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def auth_headers(db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    return {"Authorization": f"Bearer {token}"}


@patch("rag.crosscutting.security.ingestion_limits._redis_client")
def test_allows_when_under_the_threshold(mock_client):
    mock_client.incr.return_value = 3

    allowed = check_and_increment_queued_ingestion("user-1", max_queued=5)

    assert allowed is True
    mock_client.incr.assert_called_once_with("ingestion_queued:user-1")


@patch("rag.crosscutting.security.ingestion_limits._redis_client")
def test_rejects_and_decrements_when_at_the_threshold(mock_client):
    mock_client.incr.return_value = 6

    allowed = check_and_increment_queued_ingestion("user-1", max_queued=5)

    assert allowed is False
    mock_client.decr.assert_called_once_with("ingestion_queued:user-1")


@patch("rag.crosscutting.security.ingestion_limits._redis_client")
def test_decrement_calls_redis_decr(mock_client):
    decrement_queued_ingestion("user-1")

    mock_client.decr.assert_called_once_with("ingestion_queued:user-1")


@patch("rag.api.routers.documents.check_and_increment_queued_ingestion", return_value=False)
def test_upload_rejects_when_queue_limit_reached(mock_check, client, auth_headers):
    resp = client.post(
        "/api/v1/documents", headers=auth_headers,
        files={"file": ("t.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert resp.status_code == 429
