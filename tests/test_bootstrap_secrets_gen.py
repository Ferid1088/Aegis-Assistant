from cryptography.fernet import Fernet

from rag.bootstrap.secrets_gen import (
    generate_jwt_secret, generate_keystore_master_key, generate_neo4j_password, generate_postgres_password,
)


def test_generate_jwt_secret_is_nonempty_and_random():
    a = generate_jwt_secret()
    b = generate_jwt_secret()
    assert len(a) > 20
    assert a != b


def test_generate_keystore_master_key_is_valid_fernet_key():
    key = generate_keystore_master_key()
    Fernet(key.encode())  # raises if invalid


def test_generate_postgres_password_is_nonempty_and_random():
    a = generate_postgres_password()
    b = generate_postgres_password()
    assert len(a) > 10
    assert a != b


def test_generate_neo4j_password_is_nonempty_and_random():
    a = generate_neo4j_password()
    b = generate_neo4j_password()
    assert len(a) > 10
    assert a != b


def test_generate_glitchtip_secret_key_returns_a_nonempty_string():
    from rag.bootstrap.secrets_gen import generate_glitchtip_secret_key

    key = generate_glitchtip_secret_key()

    assert isinstance(key, str)
    assert len(key) > 20
