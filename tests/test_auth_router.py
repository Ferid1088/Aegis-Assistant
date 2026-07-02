import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rag.api.main import create_app
from rag.crosscutting.security.password import hash_password
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base, get_db
from rag.storage.sql.models import User


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

    shared_session.add(User(username="alice", password_hash=hash_password("correct-horse-battery-staple")))
    shared_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app, raise_server_exceptions=False)
    shared_session.close()
    engine.dispose()


def test_login_returns_tokens(client):
    resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-battery-staple"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mfa_required"] is False
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_wrong_password_returns_401(client):
    resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_me_requires_valid_token(client):
    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-battery-staple"})
    access = login.json()["access_token"]

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_full_login_mfa_refresh_logout_cycle(client):
    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-battery-staple"})
    access = login.json()["access_token"]

    enroll = client.post("/api/v1/auth/mfa/enroll", headers={"Authorization": f"Bearer {access}"})
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    login2 = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-battery-staple"})
    assert login2.json()["mfa_required"] is True
    pending = login2.json()["mfa_pending_token"]

    code = pyotp.TOTP(secret).now()
    verify = client.post("/api/v1/auth/mfa/verify", json={"mfa_pending_token": pending, "totp_code": code})
    assert verify.status_code == 200
    tokens = verify.json()

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_access = refreshed.json()["access_token"]

    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {new_access}"})
    assert logout.status_code == 204

    me_after = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me_after.status_code == 401
