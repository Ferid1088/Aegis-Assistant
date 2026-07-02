import jwt
import pytest

from rag.crosscutting.security.tokens import (
    create_access_token, create_mfa_pending_token, decode_token,
    generate_refresh_token, hash_refresh_token,
)


def test_access_token_round_trips_claims():
    token = create_access_token(user_id="u1", session_id="s1", token_version=3)
    payload = decode_token(token)
    assert payload["sub"] == "u1"
    assert payload["session_id"] == "s1"
    assert payload["tv"] == 3
    assert payload["type"] == "access"
    assert payload["kid"] == "default"


def test_mfa_pending_token_has_distinct_type():
    token = create_mfa_pending_token(user_id="u1")
    payload = decode_token(token)
    assert payload["sub"] == "u1"
    assert payload["type"] == "mfa_pending"


def test_decode_expired_token_raises():
    from rag.config import settings

    original = settings.jwt_access_ttl_seconds
    settings.jwt_access_ttl_seconds = -10  # already expired
    try:
        token = create_access_token(user_id="u1", session_id="s1", token_version=0)
    finally:
        settings.jwt_access_ttl_seconds = original

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


def test_refresh_token_hash_is_deterministic_and_not_reversible():
    raw, token_hash = generate_refresh_token()
    assert raw != token_hash
    assert hash_refresh_token(raw) == token_hash


def test_refresh_tokens_are_unique():
    raw1, _ = generate_refresh_token()
    raw2, _ = generate_refresh_token()
    assert raw1 != raw2
