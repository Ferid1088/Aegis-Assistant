import pyotp
from cryptography.fernet import Fernet, InvalidToken

from rag.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.mfa_encryption_key.encode())


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(raw_secret: str) -> bytes:
    return _fernet().encrypt(raw_secret.encode())


def decrypt_secret(encrypted: bytes) -> str:
    try:
        return _fernet().decrypt(encrypted).decode()
    except InvalidToken as exc:
        raise ValueError("could not decrypt MFA secret: invalid key or corrupted ciphertext") from exc


def totp_uri(raw_secret: str, username: str, issuer: str = "RAG Appliance") -> str:
    return pyotp.TOTP(raw_secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(raw_secret: str, code: str) -> bool:
    return pyotp.TOTP(raw_secret).verify(code, valid_window=1)
