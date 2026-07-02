from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import admin_audit
from rag.crosscutting.security.audit_events import record_admin_change
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.tokens import create_access_token
from rag.storage.sql.base import get_db
from rag.storage.sql.models import Role, RolePermission, User, UserRole, UserSession


def _make_admin_user(db_session, permission="admin:audit"):
    user = User(username="admin", password_hash=hash_password("adminpass123"))
    db_session.add(user)
    db_session.flush()
    role = Role(name=f"role-{permission}")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=permission))
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    session = UserSession(
        user_id=user.id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()
    token = create_access_token(str(user.id), str(session.id), user.token_version)
    return user, token


@pytest.fixture()
def client(db_session, tmp_path, monkeypatch):
    from rag.config import settings
    monkeypatch.setattr(settings, "audit_log_dir", str(tmp_path))

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(admin_audit.router, prefix="/api/v1/admin")
    return TestClient(app, raise_server_exceptions=False)


def test_list_audit_entries_unfiltered(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    record_admin_change("actor-1", "department_created", "department:d1")
    record_admin_change("actor-2", "role_created", "role:r1")

    resp = client.get("/api/v1/admin/audit", headers=headers)
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    assert "department_created" in actions
    assert "role_created" in actions


def test_list_audit_entries_filtered_by_actor(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    record_admin_change("actor-1", "department_created", "department:d1")
    record_admin_change("actor-2", "role_created", "role:r1")

    resp = client.get("/api/v1/admin/audit?actor=actor-1", headers=headers)
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["actor_user"] == "actor-1"


def test_list_audit_requires_permission(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:users")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/admin/audit", headers=headers)
    assert resp.status_code == 403


def test_verify_audit_chain_valid(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    record_admin_change("actor-1", "department_created", "department:d1")
    record_admin_change("actor-2", "role_created", "role:r1")

    resp = client.get("/api/v1/admin/audit/verify", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["count"] == 2
    assert body["error"] == ""


def test_verify_audit_chain_detects_tampering(client, db_session, tmp_path):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    record_admin_change("actor-1", "department_created", "department:d1")

    log_file = tmp_path / "immutable_audit.jsonl"
    content = log_file.read_text()
    tampered = content.replace("department_created", "department_deleted")
    log_file.write_text(tampered)

    resp = client.get("/api/v1/admin/audit/verify", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
