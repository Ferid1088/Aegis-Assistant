import hashlib
import secrets
import time

import jwt

from rag.config import settings

ACCESS_ALGORITHM = "HS256"
ACCESS_KID = "default"  # rotation seam for §7 — unused until a real keystore exists


def create_access_token(user_id: str, session_id: str, token_version: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "session_id": session_id,
        "tv": token_version,
        "kid": ACCESS_KID,
        "iat": now,
        "exp": now + settings.jwt_access_ttl_seconds,
        "type": "access",
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ACCESS_ALGORITHM)


def create_mfa_pending_token(user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "type": "mfa_pending",
        "iat": now,
        "exp": now + settings.jwt_mfa_pending_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ACCESS_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[ACCESS_ALGORITHM])


def generate_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
