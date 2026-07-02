import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rag.api.main import create_app
from rag.crosscutting.security.password import hash_password
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base, get_db
from rag.storage.sql.models import Role, RolePermission, User, UserRole


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
    shared_session.flush()

    admin = User(username="legal-admin", password_hash=hash_password("legal-admin-pass-1"))
    shared_session.add(admin)
    shared_session.flush()
    role = Role(name="legal-hold-admin")
    shared_session.add(role)
    shared_session.flush()
    shared_session.add(RolePermission(role_id=role.id, permission="admin:conversations"))
    shared_session.add(UserRole(user_id=admin.id, role_id=role.id))
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


def test_full_conversation_lifecycle_with_legal_hold(client):
    owner_token = _login(client, "alice", "alice-pass-12345")
    admin_token = _login(client, "legal-admin", "legal-admin-pass-1")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create_resp = client.post("/api/v1/conversations", headers=owner_headers)
    assert create_resp.status_code == 201
    conv_id = create_resp.json()["id"]

    list_resp = client.get("/api/v1/conversations", headers=owner_headers)
    assert any(c["id"] == conv_id for c in list_resp.json())

    soft_delete_resp = client.post(
        f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "soft_deleted"}, headers=owner_headers,
    )
    assert soft_delete_resp.status_code == 200
    assert soft_delete_resp.json()["state"] == "soft_deleted"

    hold_resp = client.post(
        f"/api/v1/conversations/{conv_id}/legal-hold", json={"hold": True}, headers=admin_headers,
    )
    assert hold_resp.status_code == 200
    assert hold_resp.json()["legal_hold"] is True

    erasure_resp = client.post(f"/api/v1/conversations/{conv_id}/erasure-request", headers=owner_headers)
    assert erasure_resp.status_code == 200
    assert erasure_resp.json()["action"] == "refuse"

    still_active_check = client.get(f"/api/v1/conversations/{conv_id}", headers=owner_headers)
    assert still_active_check.json()["state"] == "soft_deleted"

    unhold_resp = client.post(
        f"/api/v1/conversations/{conv_id}/legal-hold", json={"hold": False}, headers=admin_headers,
    )
    assert unhold_resp.status_code == 200
    assert unhold_resp.json()["legal_hold"] is False

    final_erasure_resp = client.post(f"/api/v1/conversations/{conv_id}/erasure-request", headers=owner_headers)
    assert final_erasure_resp.status_code == 200
    assert final_erasure_resp.json()["action"] == "purge"

    final_check = client.get(f"/api/v1/conversations/{conv_id}", headers=owner_headers)
    assert final_check.json()["state"] == "purged"


def test_conversation_endpoints_require_authentication(client):
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 401
