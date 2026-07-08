import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rag.api.main import create_app
from rag.auth.password import hash_password
from rag.infra.stores.sql import models  # noqa: F401
from rag.infra.stores.sql.base import Base, get_db
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole


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

    admin = User(username="root-admin", password_hash=hash_password("root-admin-pass-123"))
    shared_session.add(admin)
    shared_session.flush()
    admin_role = Role(name="super-admin")
    shared_session.add(admin_role)
    shared_session.flush()
    for perm in ["admin:departments", "admin:roles", "admin:users"]:
        shared_session.add(RolePermission(role_id=admin_role.id, permission=perm))
    shared_session.add(UserRole(user_id=admin.id, role_id=admin_role.id))
    shared_session.add(User(username="target", password_hash=hash_password("target-pass-12345")))
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


def test_full_rbac_chain_takes_effect_on_next_request(client):
    admin_token = _login(client, "root-admin", "root-admin-pass-123")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    dept = client.post("/api/v1/admin/departments", json={"name": "HR"}, headers=admin_headers).json()
    level = client.post(
        f"/api/v1/admin/departments/{dept['id']}/access-levels", json={"label": "HR_L1", "rank": 1}, headers=admin_headers,
    ).json()
    role = client.post("/api/v1/admin/roles", json={"name": "hr_analyst"}, headers=admin_headers).json()

    grant_resp = client.post(
        f"/api/v1/admin/roles/{role['id']}/grants", json={"access_level_id": level["id"]}, headers=admin_headers,
    )
    assert grant_resp.status_code == 201

    target_users = client.get("/api/v1/admin/users", headers=admin_headers).json()
    target = next(u for u in target_users if u["username"] == "target")

    assign_resp = client.post(
        f"/api/v1/admin/users/{target['id']}/roles", json={"role_id": role["id"]}, headers=admin_headers,
    )
    assert assign_resp.status_code == 201

    target_token = _login(client, "target", "target-pass-12345")
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {target_token}"})
    assert me.status_code == 200
    body = me.json()
    assert "hr_analyst" in body["roles"]
    assert "HR_L1" in body["effective_levels"]


def test_revoking_a_grant_takes_effect_immediately_with_no_caching(client):
    admin_token = _login(client, "root-admin", "root-admin-pass-123")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    dept = client.post("/api/v1/admin/departments", json={"name": "Legal"}, headers=admin_headers).json()
    level = client.post(
        f"/api/v1/admin/departments/{dept['id']}/access-levels", json={"label": "LEGAL_L1", "rank": 1}, headers=admin_headers,
    ).json()
    role = client.post("/api/v1/admin/roles", json={"name": "legal_analyst"}, headers=admin_headers).json()
    client.post(f"/api/v1/admin/roles/{role['id']}/grants", json={"access_level_id": level["id"]}, headers=admin_headers)

    target_users = client.get("/api/v1/admin/users", headers=admin_headers).json()
    target = next(u for u in target_users if u["username"] == "target")
    client.post(f"/api/v1/admin/users/{target['id']}/roles", json={"role_id": role["id"]}, headers=admin_headers)

    target_token = _login(client, "target", "target-pass-12345")
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {target_token}"})
    assert "LEGAL_L1" in me.json()["effective_levels"]

    revoke_resp = client.delete(f"/api/v1/admin/roles/{role['id']}/grants/{level['id']}", headers=admin_headers)
    assert revoke_resp.status_code == 204

    me_after = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {target_token}"})
    assert "LEGAL_L1" not in me_after.json()["effective_levels"]


def test_admin_endpoints_require_authentication(client):
    resp = client.get("/api/v1/admin/departments")
    assert resp.status_code == 401
