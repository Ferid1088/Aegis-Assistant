import pyotp
import pytest
from cryptography.fernet import Fernet

from rag.crosscutting.security.mfa import (
    decrypt_secret, encrypt_secret, generate_totp_secret, totp_uri, verify_totp,
)


def test_generate_totp_secret_is_valid_base32():
    secret = generate_totp_secret()
    assert len(secret) >= 16
    pyotp.TOTP(secret)  # raises if not valid base32


def test_encrypt_decrypt_round_trip(db_session):
    secret = generate_totp_secret()
    encrypted = encrypt_secret(db_session, secret)
    assert encrypted != secret.encode()
    assert decrypt_secret(db_session, encrypted) == secret


def test_verify_totp_accepts_current_code():
    secret = generate_totp_secret()
    current_code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, current_code) is True


def test_verify_totp_rejects_wrong_code():
    secret = generate_totp_secret()
    assert verify_totp(secret, "000000") is False


def test_totp_uri_contains_username_and_issuer():
    secret = generate_totp_secret()
    uri = totp_uri(secret, "alice", issuer="RAG Appliance")
    assert "alice" in uri
    assert "RAG%20Appliance" in uri or "RAG Appliance" in uri


def test_decrypt_secret_with_wrong_key_raises_value_error(db_session):
    """Ciphertext encrypted under an unrelated key must fail cleanly, not raise the
    raw cryptography.fernet.InvalidToken exception."""
    secret = generate_totp_secret()
    encrypted_with_other_key = Fernet(Fernet.generate_key()).encrypt(secret.encode())

    with pytest.raises(ValueError):
        decrypt_secret(db_session, encrypted_with_other_key)


def test_decrypt_secret_with_corrupted_ciphertext_raises_value_error(db_session):
    secret = generate_totp_secret()
    encrypted = bytearray(encrypt_secret(db_session, secret))
    encrypted[-1] ^= 0xFF  # flip bits to corrupt the ciphertext/HMAC

    with pytest.raises(ValueError):
        decrypt_secret(db_session, bytes(encrypted))
