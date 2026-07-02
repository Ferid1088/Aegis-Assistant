from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import admin_users
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.tokens import create_access_token
from rag.storage.sql.base import get_db
from rag.storage.sql.models import Department, Role, RolePermission, User, UserRole, UserSession


def _make_admin_user(db_session, permission="admin:users"):
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
def client(db_session):
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(admin_users.router, prefix="/api/v1/admin")
    return TestClient(app, raise_server_exceptions=False)


def test_create_list_get_user(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/users", json={"username": "alice", "email": "alice@example.com", "password": "correct-horse-battery-staple"}, headers=headers)
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    assert resp.json()["username"] == "alice"

    resp = client.get("/api/v1/admin/users", headers=headers)
    assert any(u["id"] == user_id for u in resp.json())

    resp = client.get(f"/api/v1/admin/users/{user_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


def test_create_user_without_password_is_sso_only(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/users", json={"username": "bob"}, headers=headers)
    assert resp.status_code == 201


def test_create_duplicate_username_409s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/api/v1/admin/users", json={"username": "carol"}, headers=headers)
    resp = client.post("/api/v1/admin/users", json={"username": "carol"}, headers=headers)
    assert resp.status_code == 409


def test_create_user_with_unknown_department_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post("/api/v1/admin/users", json={"username": "dave", "department_id": fake_id}, headers=headers)
    assert resp.status_code == 404


def test_update_user(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    dept = Department(name="HR")
    db_session.add(dept)
    db_session.commit()

    resp = client.post("/api/v1/admin/users", json={"username": "erin"}, headers=headers)
    user_id = resp.json()["id"]

    resp = client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"email": "erin@example.com", "department_id": str(dept.id), "is_active": False},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "erin@example.com"
    assert body["department_id"] == str(dept.id)
    assert body["is_active"] is False


def test_get_unknown_user_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.get(f"/api/v1/admin/users/{fake_id}", headers=headers)
    assert resp.status_code == 404


def test_assign_and_remove_role(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/users", json={"username": "frank"}, headers=headers)
    user_id = resp.json()["id"]

    role = Role(name="frank_role")
    db_session.add(role)
    db_session.commit()

    resp = client.post(f"/api/v1/admin/users/{user_id}/roles", json={"role_id": str(role.id)}, headers=headers)
    assert resp.status_code == 201

    resp = client.post(f"/api/v1/admin/users/{user_id}/roles", json={"role_id": str(role.id)}, headers=headers)
    assert resp.status_code == 409

    resp = client.delete(f"/api/v1/admin/users/{user_id}/roles/{role.id}", headers=headers)
    assert resp.status_code == 204

    resp = client.delete(f"/api/v1/admin/users/{user_id}/roles/{role.id}", headers=headers)
    assert resp.status_code == 404


def test_assign_unknown_role_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post("/api/v1/admin/users", json={"username": "grace"}, headers=headers)
    user_id = resp.json()["id"]

    resp = client.post(f"/api/v1/admin/users/{user_id}/roles", json={"role_id": fake_id}, headers=headers)
    assert resp.status_code == 404
