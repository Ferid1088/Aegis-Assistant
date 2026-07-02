from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rag.api.deps import get_current_user
from rag.crosscutting.security.tokens import create_access_token
from rag.storage.sql.base import get_db
from rag.storage.sql.models import User, UserSession


def _app_with_protected_route(db_session):
    app = FastAPI()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/protected")
    def protected_route(current=Depends(get_current_user)):
        return {"username": current.user.username}

    return app


def _make_user_and_session(db_session, username="alice"):
    user = User(username=username)
    db_session.add(user)
    db_session.flush()
    session = UserSession(
        user_id=user.id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()
    return user, session


def test_valid_token_resolves_current_user(db_session):
    user, session = _make_user_and_session(db_session)
    token = create_access_token(str(user.id), str(session.id), user.token_version)

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_missing_header_is_rejected(db_session):
    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_revoked_session_is_rejected(db_session):
    user, session = _make_user_and_session(db_session)
    token = create_access_token(str(user.id), str(session.id), user.token_version)
    session.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_stale_token_version_is_rejected(db_session):
    user, session = _make_user_and_session(db_session)
    token = create_access_token(str(user.id), str(session.id), user.token_version)
    user.token_version += 1  # e.g. a password reset happened
    db_session.commit()

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
