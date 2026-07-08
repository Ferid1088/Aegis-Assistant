import base64

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from rag.crosscutting.security.keystore import get_or_create_key


def _fernet(db: Session) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(get_or_create_key(db, "mfa")))


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(db: Session, raw_secret: str) -> bytes:
    return _fernet(db).encrypt(raw_secret.encode())


def decrypt_secret(db: Session, encrypted: bytes) -> str:
    try:
        return _fernet(db).decrypt(encrypted).decode()
    except InvalidToken as exc:
        raise ValueError("could not decrypt MFA secret: invalid key or corrupted ciphertext") from exc


def totp_uri(raw_secret: str, username: str, issuer: str = "RAG Appliance") -> str:
    return pyotp.TOTP(raw_secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(raw_secret: str, code: str) -> bool:
    return pyotp.TOTP(raw_secret).verify(code, valid_window=1)
