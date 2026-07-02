from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import conversations
from rag.crosscutting.security.tokens import create_access_token
from rag.storage.sql.base import get_db
from rag.storage.sql.models import User, UserSession


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


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(conversations.router, prefix="/api/v1/conversations")
    return TestClient(app, raise_server_exceptions=False)


def test_create_and_get_conversation(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/conversations", headers=headers)
    assert resp.status_code == 201
    conv_id = resp.json()["id"]
    assert resp.json()["state"] == "active"

    resp = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == conv_id


def test_get_conversation_not_owned_by_caller_404s(client, db_session):
    _, alice_token = _make_user_with_token(db_session, "alice")
    _, mallory_token = _make_user_with_token(db_session, "mallory")

    resp = client.post("/api/v1/conversations", headers={"Authorization": f"Bearer {alice_token}"})
    conv_id = resp.json()["id"]

    resp = client.get(f"/api/v1/conversations/{conv_id}", headers={"Authorization": f"Bearer {mallory_token}"})
    assert resp.status_code == 404


def test_list_conversations_returns_only_callers_own(client, db_session):
    _, alice_token = _make_user_with_token(db_session, "alice")
    _, mallory_token = _make_user_with_token(db_session, "mallory")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    client.post("/api/v1/conversations", headers=alice_headers)
    client.post("/api/v1/conversations", headers=alice_headers)
    client.post("/api/v1/conversations", headers={"Authorization": f"Bearer {mallory_token}"})

    resp = client.get("/api/v1/conversations", headers=alice_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_transition_conversation(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "archived"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "archived"


def test_transition_to_invalid_state_name_422s(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "not-a-real-state"}, headers=headers)
    assert resp.status_code == 422


def test_transition_disallowed_by_state_machine_409s(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "purged"}, headers=headers)
    assert resp.status_code == 409


def test_erasure_request_purges(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]
    client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "soft_deleted"}, headers=headers)

    resp = client.post(f"/api/v1/conversations/{conv_id}/erasure-request", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["action"] == "purge"

    resp = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert resp.json()["state"] == "purged"


def test_endpoints_require_authentication(client, db_session):
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 401
