import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from rag.api.routers import setup
from rag.crosscutting.security.password import verify_password
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import RolePermission, User, UserRole


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(setup.router, prefix="/api/v1/setup")
    return TestClient(app, raise_server_exceptions=False)


def test_status_needs_setup_true_on_empty_db(client):
    resp = client.get("/api/v1/setup/status")
    assert resp.status_code == 200
    assert resp.json() == {"needs_setup": True}


def test_create_admin_on_empty_db(client, db_session):
    resp = client.post("/api/v1/setup/admin", json={"username": "boss", "password": "correct-horse-battery"})
    assert resp.status_code == 201
    assert resp.json() == {"ok": True}

    user = db_session.execute(select(User).where(User.username == "boss")).scalar_one()
    assert verify_password("correct-horse-battery", user.password_hash) is True

    role_ids = [
        r.role_id for r in db_session.execute(select(UserRole).where(UserRole.user_id == user.id)).scalars().all()
    ]
    assert len(role_ids) == 1
    granted = set(
        db_session.execute(select(RolePermission.permission).where(RolePermission.role_id == role_ids[0])).scalars().all()
    )
    assert granted == set(setup.ADMIN_PERMISSIONS)


def test_status_needs_setup_false_after_admin_created(client):
    client.post("/api/v1/setup/admin", json={"username": "boss", "password": "correct-horse-battery"})
    resp = client.get("/api/v1/setup/status")
    assert resp.json() == {"needs_setup": False}


def test_create_admin_rejects_short_password(client, db_session):
    resp = client.post("/api/v1/setup/admin", json={"username": "boss", "password": "short"})
    assert resp.status_code == 422

    all_users = db_session.execute(select(User)).scalars().all()
    assert all_users == []


def test_create_admin_409s_once_admin_exists(client, db_session):
    first = client.post("/api/v1/setup/admin", json={"username": "boss", "password": "correct-horse-battery"})
    assert first.status_code == 201

    second = client.post("/api/v1/setup/admin", json={"username": "someone-else", "password": "correct-horse-battery"})
    assert second.status_code == 409

    all_users = db_session.execute(select(User)).scalars().all()
    assert len(all_users) == 1
