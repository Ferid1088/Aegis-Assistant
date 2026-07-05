import secrets

from cryptography.fernet import Fernet


def generate_jwt_secret() -> str:
    return secrets.token_urlsafe(48)


def generate_keystore_master_key() -> str:
    return Fernet.generate_key().decode()


def generate_postgres_password() -> str:
    return secrets.token_urlsafe(24)


def generate_neo4j_password() -> str:
    return secrets.token_urlsafe(24)
