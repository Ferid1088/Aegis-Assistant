import pytest
from cryptography.fernet import Fernet

from rag.config import settings
from rag.crosscutting.security import local_auth
from rag.crosscutting.security.mfa import encrypt_secret, generate_totp_secret
from rag.crosscutting.security.password import hash_password
from rag.crosscutting.security.tokens import decode_token
from rag.infra.stores.sql.models import User


@pytest.fixture(autouse=True)
def _audit_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audit_log_dir", str(tmp_path))


def _make_active_user(db_session, username="alice", password="correct-horse-battery-staple", mfa=False):
    user = User(username=username, password_hash=hash_password(password))
    if mfa:
        secret = generate_totp_secret()
        user.mfa_enabled = True
        user.mfa_secret_encrypted = encrypt_secret(db_session, secret)
        db_session.add(user)
        db_session.commit()
        return user, secret
    db_session.add(user)
    db_session.commit()
    return user, None


def test_login_success_without_mfa_issues_tokens(db_session):
    _make_active_user(db_session)

    result = local_auth.login(db_session, "alice", "correct-horse-battery-staple")

    assert result.mfa_required is False
    assert result.access_token is not None
    assert result.refresh_token is not None
    payload = decode_token(result.access_token)
    assert payload["sub"] is not None


def test_login_success_with_mfa_returns_pending_token(db_session):
    _make_active_user(db_session, mfa=True)

    result = local_auth.login(db_session, "alice", "correct-horse-battery-staple")

    assert result.mfa_required is True
    assert result.mfa_pending_token is not None
    assert result.access_token is None


def test_login_wrong_password_raises_auth_error(db_session):
    _make_active_user(db_session)

    with pytest.raises(local_auth.AuthError):
        local_auth.login(db_session, "alice", "wrong-password")


def test_login_unknown_username_raises_auth_error(db_session):
    with pytest.raises(local_auth.AuthError):
        local_auth.login(db_session, "nobody", "whatever")


def test_repeated_failures_lock_the_account(db_session):
    _make_active_user(db_session)

    for _ in range(settings.lockout_threshold):
        with pytest.raises(local_auth.AuthError):
            local_auth.login(db_session, "alice", "wrong-password")

    with pytest.raises(local_auth.AuthError, match="locked"):
        local_auth.login(db_session, "alice", "correct-horse-battery-staple")


def test_verify_mfa_with_correct_code_issues_tokens(db_session):
    _, secret = _make_active_user(db_session, mfa=True)
    login_result = local_auth.login(db_session, "alice", "correct-horse-battery-staple")

    import pyotp
    code = pyotp.TOTP(secret).now()
    final = local_auth.verify_mfa(db_session, login_result.mfa_pending_token, code)

    assert final.access_token is not None
    assert final.refresh_token is not None


def test_verify_mfa_with_wrong_code_raises(db_session):
    _make_active_user(db_session, mfa=True)
    login_result = local_auth.login(db_session, "alice", "correct-horse-battery-staple")

    with pytest.raises(local_auth.AuthError):
        local_auth.verify_mfa(db_session, login_result.mfa_pending_token, "000000")


def test_verify_mfa_rejects_access_token_in_place_of_pending_token(db_session):
    """An already-issued access token (e.g. from a non-MFA account, or replayed
    after full login) must never be usable as an MFA-pending token."""
    _make_active_user(db_session)
    result = local_auth.login(db_session, "alice", "correct-horse-battery-staple")

    with pytest.raises(local_auth.AuthError):
        local_auth.verify_mfa(db_session, result.access_token, "000000")


def test_verify_mfa_with_undecryptable_secret_raises_auth_error_not_500(db_session):
    """If mfa_encryption_key was rotated (or the ciphertext is corrupted), decrypt_secret
    raises ValueError; verify_mfa must translate that into a clean AuthError, not let it
    propagate as an unhandled exception."""
    user = User(username="alice", password_hash=hash_password("correct-horse-battery-staple"))
    secret = generate_totp_secret()
    user.mfa_enabled = True
    # Encrypted with a different key than settings.mfa_encryption_key -> undecryptable.
    user.mfa_secret_encrypted = Fernet(Fernet.generate_key()).encrypt(secret.encode())
    db_session.add(user)
    db_session.commit()

    login_result = local_auth.login(db_session, "alice", "correct-horse-battery-staple")
    assert login_result.mfa_required is True

    import pyotp
    code = pyotp.TOTP(secret).now()
    with pytest.raises(local_auth.AuthError):
        local_auth.verify_mfa(db_session, login_result.mfa_pending_token, code)
