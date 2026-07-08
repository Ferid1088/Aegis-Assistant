import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rag.api.deps import get_current_user, require_permission, require_any_permission
from rag.config import settings
from rag.crosscutting.security.tokens import ACCESS_ALGORITHM, create_access_token, create_mfa_pending_token
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import User, UserSession, Role, RolePermission, UserRole


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


def test_expired_token_is_rejected(db_session):
    from rag.config import settings

    user, session = _make_user_and_session(db_session)

    original = settings.jwt_access_ttl_seconds
    settings.jwt_access_ttl_seconds = -10  # already expired
    try:
        token = create_access_token(str(user.id), str(session.id), user.token_version)
    finally:
        settings.jwt_access_ttl_seconds = original

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_token_type_is_rejected(db_session):
    user, _session = _make_user_and_session(db_session)
    token = create_mfa_pending_token(str(user.id))

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_inactive_user_is_rejected(db_session):
    user, session = _make_user_and_session(db_session)
    user.is_active = False
    db_session.commit()
    token = create_access_token(str(user.id), str(session.id), user.token_version)

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def _encode_raw(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ACCESS_ALGORITHM)


def test_token_with_missing_sub_claim_is_rejected_not_500(db_session):
    _user, session = _make_user_and_session(db_session)
    now = int(time.time())
    token = _encode_raw({
        "session_id": str(session.id), "tv": 0, "type": "access",
        "iat": now, "exp": now + 300,
    })

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_with_non_uuid_sub_is_rejected_not_500(db_session):
    now = int(time.time())
    token = _encode_raw({
        "sub": "not-a-uuid", "session_id": str(uuid.uuid4()), "tv": 0,
        "type": "access", "iat": now, "exp": now + 300,
    })

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_with_non_uuid_session_id_is_rejected_not_500(db_session):
    user, _session = _make_user_and_session(db_session)
    now = int(time.time())
    token = _encode_raw({
        "sub": str(user.id), "session_id": "not-a-uuid", "tv": user.token_version,
        "type": "access", "iat": now, "exp": now + 300,
    })

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_with_missing_session_id_claim_is_rejected_not_500(db_session):
    user, _session = _make_user_and_session(db_session)
    now = int(time.time())
    token = _encode_raw({
        "sub": str(user.id), "tv": user.token_version,
        "type": "access", "iat": now, "exp": now + 300,
    })

    app = _app_with_protected_route(db_session)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def _grant_permission(db_session, user, permission):
    role = Role(name=f"role-{permission}")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=permission))
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()


def test_require_permission_allows_when_granted(db_session):
    user, session = _make_user_and_session(db_session)
    _grant_permission(db_session, user, "admin:users")
    token = create_access_token(str(user.id), str(session.id), user.token_version)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session

    @app.get("/needs-perm")
    def protected_route(current=Depends(require_permission("admin:users"))):
        return {"username": current.user.username}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/needs-perm", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_require_permission_rejects_when_not_granted(db_session):
    user, session = _make_user_and_session(db_session)
    token = create_access_token(str(user.id), str(session.id), user.token_version)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session

    @app.get("/needs-perm")
    def protected_route(current=Depends(require_permission("admin:users"))):
        return {"username": current.user.username}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/needs-perm", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_require_any_permission_allows_when_any_granted(db_session):
    user, session = _make_user_and_session(db_session)
    _grant_permission(db_session, user, "documents:manage_versions")
    token = create_access_token(str(user.id), str(session.id), user.token_version)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session

    @app.get("/needs-any-perm")
    def protected_route(current=Depends(require_any_permission("admin:departments", "documents:manage_versions"))):
        return {"username": current.user.username}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/needs-any-perm", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_require_any_permission_rejects_when_none_granted(db_session):
    user, session = _make_user_and_session(db_session)
    token = create_access_token(str(user.id), str(session.id), user.token_version)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session

    @app.get("/needs-any-perm")
    def protected_route(current=Depends(require_any_permission("admin:departments", "documents:manage_versions"))):
        return {"username": current.user.username}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/needs-any-perm", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
