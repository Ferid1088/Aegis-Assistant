import uuid

import pytest

from rag.config import settings
from rag.crosscutting.security import local_auth, session_service
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.tokens import decode_token, hash_refresh_token
from rag.storage.sql.models import RefreshToken, User, UserSession


@pytest.fixture(autouse=True)
def _audit_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audit_log_dir", str(tmp_path))


def _login(db_session, username="alice", password="correct-horse-battery-staple"):
    user = User(username=username, password_hash=hash_password(password))
    db_session.add(user)
    db_session.commit()
    return local_auth.login(db_session, username, password)


def test_refresh_rotates_token_and_issues_new_access_token(db_session):
    result = _login(db_session)

    new_access, new_refresh = session_service.refresh(db_session, result.refresh_token)

    assert new_access != result.access_token
    assert new_refresh != result.refresh_token

    old_hash = hash_refresh_token(result.refresh_token)
    old_row = db_session.query(RefreshToken).filter_by(token_hash=old_hash).one()
    assert old_row.revoked_at is not None
    assert old_row.replaced_by is not None


def test_refresh_with_already_used_token_fails(db_session):
    result = _login(db_session)
    session_service.refresh(db_session, result.refresh_token)

    with pytest.raises(session_service.SessionError):
        session_service.refresh(db_session, result.refresh_token)


def test_refresh_with_unknown_token_fails(db_session):
    with pytest.raises(session_service.SessionError):
        session_service.refresh(db_session, "not-a-real-token")


def test_logout_revokes_session_and_its_refresh_tokens(db_session):
    result = _login(db_session)
    payload = decode_token(result.access_token)
    session_id = payload["session_id"]

    session_service.logout(db_session, session_id, payload["sub"])

    session = db_session.query(UserSession).filter_by(id=uuid.UUID(session_id)).one()
    assert session.revoked_at is not None

    with pytest.raises(session_service.SessionError):
        session_service.refresh(db_session, result.refresh_token)


def test_revoke_all_sessions_revokes_every_active_session_and_bumps_token_version(db_session):
    user = User(username="multi-session-user", password_hash=hash_password("correct-horse-battery-staple"))
    db_session.add(user)
    db_session.commit()

    result_a = local_auth.login(db_session, "multi-session-user", "correct-horse-battery-staple")
    result_b = local_auth.login(db_session, "multi-session-user", "correct-horse-battery-staple")

    original_token_version = user.token_version
    count = session_service.revoke_all_sessions(db_session, user.id, "admin-actor")
    assert count == 2

    db_session.refresh(user)
    assert user.token_version == original_token_version + 1

    with pytest.raises(session_service.SessionError):
        session_service.refresh(db_session, result_a.refresh_token)
    with pytest.raises(session_service.SessionError):
        session_service.refresh(db_session, result_b.refresh_token)
