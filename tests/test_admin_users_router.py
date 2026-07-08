from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rag.api.deps import get_current_user
from rag.api.routers import admin_users
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.tokens import create_access_token
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import Department, Role, RolePermission, User, UserRole, UserSession


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


def test_lock_and_unlock_user(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/users", json={"username": "heidi"}, headers=headers)
    user_id = resp.json()["id"]

    resp = client.post(f"/api/v1/admin/users/{user_id}/lock", json={"reason": "suspected compromise"}, headers=headers)
    assert resp.status_code == 204

    locked_user = db_session.get(User, uuid.UUID(user_id))
    assert locked_user.locked_until is not None
    assert locked_user.lock_reason == "suspected compromise"

    resp = client.post(f"/api/v1/admin/users/{user_id}/unlock", headers=headers)
    assert resp.status_code == 204

    db_session.refresh(locked_user)
    assert locked_user.locked_until is None
    assert locked_user.lock_reason is None
    assert locked_user.failed_login_count == 0


def test_lock_unknown_user_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post(f"/api/v1/admin/users/{fake_id}/lock", json={"reason": "x"}, headers=headers)
    assert resp.status_code == 404


def test_list_sessions_returns_only_active_sessions(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/users", json={"username": "ivan"}, headers=headers)
    user_id = uuid.UUID(resp.json()["id"])

    active = UserSession(
        user_id=user_id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ip="127.0.0.1", user_agent="pytest",
    )
    revoked = UserSession(
        user_id=user_id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        revoked_at=datetime.now(timezone.utc),
    )
    db_session.add_all([active, revoked])
    db_session.commit()

    resp = client.get(f"/api/v1/admin/users/{user_id}/sessions", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(active.id)
    assert body[0]["ip"] == "127.0.0.1"
    assert body[0]["user_agent"] == "pytest"


def test_list_sessions_unknown_user_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.get(f"/api/v1/admin/users/{fake_id}/sessions", headers=headers)
    assert resp.status_code == 404


def test_revoke_all_sessions_endpoint_bumps_token_version_and_revokes_sessions(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/users", json={"username": "judy"}, headers=headers)
    user_id = uuid.UUID(resp.json()["id"])
    target_user = db_session.get(User, user_id)
    original_token_version = target_user.token_version

    db_session.add_all([
        UserSession(
            user_id=user_id, issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
        UserSession(
            user_id=user_id, issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    ])
    db_session.commit()

    resp = client.delete(f"/api/v1/admin/users/{user_id}/sessions", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"revoked_count": 2}

    db_session.refresh(target_user)
    assert target_user.token_version == original_token_version + 1

    resp = client.get(f"/api/v1/admin/users/{user_id}/sessions", headers=headers)
    assert resp.json() == []


def test_revoke_all_sessions_unknown_user_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(f"/api/v1/admin/users/{fake_id}/sessions", headers=headers)
    assert resp.status_code == 404


def test_revoke_all_sessions_invalidates_a_live_access_token(client, db_session):
    admin_user, admin_token = _make_admin_user(db_session)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Create a non-admin target user and mint a real access token for them,
    # the same way _make_admin_user does but without granting any permission.
    target = User(username="kevin", password_hash=hash_password("targetpass123"))
    db_session.add(target)
    db_session.flush()
    target_session = UserSession(
        user_id=target.id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(target_session)
    db_session.commit()
    target_token = create_access_token(str(target.id), str(target_session.id), target.token_version)

    # Build an isolated app with a protected route depending on get_current_user,
    # following the same pattern used in tests/test_api_deps.py, but backed by
    # the same db_session used by the `client` fixture so state is shared.
    protected_app = FastAPI()
    protected_app.dependency_overrides[get_db] = lambda: db_session

    @protected_app.get("/protected")
    def protected_route(current=Depends(get_current_user)):
        return {"username": current.user.username}

    protected_client = TestClient(protected_app, raise_server_exceptions=False)
    target_headers = {"Authorization": f"Bearer {target_token}"}

    # Sanity check: the token currently works.
    resp = protected_client.get("/protected", headers=target_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "kevin"

    # Revoke all of the target's sessions via the admin endpoint.
    resp = client.delete(f"/api/v1/admin/users/{target.id}/sessions", headers=admin_headers)
    assert resp.status_code == 200

    # The same, previously-valid access token must now be rejected.
    resp = protected_client.get("/protected", headers=target_headers)
    assert resp.status_code == 401
