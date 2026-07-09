import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import admin_rbac
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.tokens import create_access_token
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole, UserSession


def _make_admin_user(db_session, permission="admin:departments"):
    user = User(username=f"admin-{uuid.uuid4().hex[:8]}", password_hash=hash_password("adminpass123"))
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
    app.include_router(admin_rbac.router, prefix="/api/v1/admin")
    return TestClient(app, raise_server_exceptions=False)


def test_create_and_list_departments(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/departments", json={"name": "HR"}, headers=headers)
    assert resp.status_code == 201
    dept_id = resp.json()["id"]

    resp = client.get("/api/v1/admin/departments", headers=headers)
    assert resp.status_code == 200
    assert any(d["id"] == dept_id for d in resp.json())


def test_create_department_requires_permission(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:users")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/departments", json={"name": "HR"}, headers=headers)
    assert resp.status_code == 403


def test_delete_department(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/departments", json={"name": "Legal"}, headers=headers)
    dept_id = resp.json()["id"]

    resp = client.delete(f"/api/v1/admin/departments/{dept_id}", headers=headers)
    assert resp.status_code == 204

    resp = client.get("/api/v1/admin/departments", headers=headers)
    assert not any(d["id"] == dept_id for d in resp.json())


def test_delete_unknown_department_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(f"/api/v1/admin/departments/{fake_id}", headers=headers)
    assert resp.status_code == 404


def test_create_and_delete_access_level(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/departments", json={"name": "Finance"}, headers=headers)
    dept_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/admin/departments/{dept_id}/access-levels", json={"label": "FIN_L1", "rank": 1}, headers=headers,
    )
    assert resp.status_code == 201
    level_id = resp.json()["id"]
    assert resp.json()["department_id"] == dept_id

    resp = client.delete(f"/api/v1/admin/access-levels/{level_id}", headers=headers)
    assert resp.status_code == 204


def test_list_access_levels_for_department(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/departments", json={"name": "HR"}, headers=headers)
    dept_id = resp.json()["id"]
    client.post(f"/api/v1/admin/departments/{dept_id}/access-levels", json={"label": "Public", "rank": 1}, headers=headers)
    client.post(f"/api/v1/admin/departments/{dept_id}/access-levels", json={"label": "Confidential", "rank": 2}, headers=headers)

    resp = client.get(f"/api/v1/admin/departments/{dept_id}/access-levels", headers=headers)
    assert resp.status_code == 200
    labels = {level["label"] for level in resp.json()}
    assert labels == {"Public", "Confidential"}
    assert all(level["department_id"] == dept_id for level in resp.json())


def test_list_access_levels_for_unknown_department_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/admin/departments/00000000-0000-0000-0000-000000000000/access-levels", headers=headers)
    assert resp.status_code == 404


def test_create_access_level_for_unknown_department_404s(client, db_session):
    _, token = _make_admin_user(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post(
        f"/api/v1/admin/departments/{fake_id}/access-levels", json={"label": "X", "rank": 1}, headers=headers,
    )
    assert resp.status_code == 404


def test_create_and_list_roles(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:roles")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/roles", json={"name": "hr_analyst"}, headers=headers)
    assert resp.status_code == 201
    role_id = resp.json()["id"]

    resp = client.get("/api/v1/admin/roles", headers=headers)
    assert any(r["id"] == role_id for r in resp.json())


def test_delete_role(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:roles")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/roles", json={"name": "temp_role"}, headers=headers)
    role_id = resp.json()["id"]

    resp = client.delete(f"/api/v1/admin/roles/{role_id}", headers=headers)
    assert resp.status_code == 204


def test_grant_and_revoke_access_level(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:roles")
    headers = {"Authorization": f"Bearer {token}"}
    _, dept_token = _make_admin_user(db_session, permission="admin:departments")
    dept_headers = {"Authorization": f"Bearer {dept_token}"}

    dept = client.post("/api/v1/admin/departments", json={"name": "HR"}, headers=dept_headers).json()
    level = client.post(
        f"/api/v1/admin/departments/{dept['id']}/access-levels", json={"label": "HR_L1", "rank": 1}, headers=dept_headers,
    ).json()
    role = client.post("/api/v1/admin/roles", json={"name": "hr_role"}, headers=headers).json()

    resp = client.post(f"/api/v1/admin/roles/{role['id']}/grants", json={"access_level_id": level["id"]}, headers=headers)
    assert resp.status_code == 201

    resp = client.post(f"/api/v1/admin/roles/{role['id']}/grants", json={"access_level_id": level["id"]}, headers=headers)
    assert resp.status_code == 409

    resp = client.delete(f"/api/v1/admin/roles/{role['id']}/grants/{level['id']}", headers=headers)
    assert resp.status_code == 204

    resp = client.delete(f"/api/v1/admin/roles/{role['id']}/grants/{level['id']}", headers=headers)
    assert resp.status_code == 404


def test_grant_and_revoke_permission(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:roles")
    headers = {"Authorization": f"Bearer {token}"}

    role = client.post("/api/v1/admin/roles", json={"name": "perm_role"}, headers=headers).json()

    resp = client.post(f"/api/v1/admin/roles/{role['id']}/permissions", json={"permission": "admin:users"}, headers=headers)
    assert resp.status_code == 201

    resp = client.post(f"/api/v1/admin/roles/{role['id']}/permissions", json={"permission": "admin:users"}, headers=headers)
    assert resp.status_code == 409

    resp = client.delete(f"/api/v1/admin/roles/{role['id']}/permissions/admin:users", headers=headers)
    assert resp.status_code == 204


def test_create_list_and_delete_document_type(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:document_types")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/admin/document-types", json={"label": "manual"}, headers=headers)
    assert resp.status_code == 201
    dt_id = resp.json()["id"]

    resp = client.get("/api/v1/admin/document-types", headers=headers)
    assert any(d["id"] == dt_id for d in resp.json())

    resp = client.delete(f"/api/v1/admin/document-types/{dt_id}", headers=headers)
    assert resp.status_code == 204


def test_list_departments_allows_documents_upload_permission(client, db_session):
    _, token = _make_admin_user(db_session, permission="documents:upload")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/admin/departments", headers=headers)
    assert resp.status_code == 200


def test_list_departments_still_rejects_unrelated_permission(client, db_session):
    _, token = _make_admin_user(db_session, permission="admin:users")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/admin/departments", headers=headers)
    assert resp.status_code == 403
