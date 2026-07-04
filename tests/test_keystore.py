from rag.crosscutting.security import keystore


def test_get_or_create_key_generates_and_persists(db_session):
    key1 = keystore.get_or_create_key(db_session, "test-purpose")
    key2 = keystore.get_or_create_key(db_session, "test-purpose")
    assert key1 == key2
    assert len(key1) > 0


def test_different_purposes_get_different_keys(db_session):
    key_a = keystore.get_or_create_key(db_session, "purpose-a")
    key_b = keystore.get_or_create_key(db_session, "purpose-b")
    assert key_a != key_b


def test_rotate_master_key_preserves_dek_values(db_session, monkeypatch):
    from cryptography.fernet import Fernet
    from rag import config

    original_key = keystore.get_or_create_key(db_session, "rotation-test")

    new_master_key = Fernet.generate_key()
    keystore.rotate_master_key(db_session, new_master_key)
    monkeypatch.setattr(config.settings, "keystore_master_key", new_master_key.decode())

    key_after_rotation = keystore.get_or_create_key(db_session, "rotation-test")
    assert key_after_rotation == original_key


def test_rotate_master_key_sets_rotated_at(db_session, monkeypatch):
    from cryptography.fernet import Fernet
    from rag import config
    from rag.storage.sql.models import KeystoreKey

    keystore.get_or_create_key(db_session, "rotation-test")

    # Before rotation, rotated_at should be None
    row_before = db_session.get(KeystoreKey, "rotation-test")
    assert row_before.rotated_at is None

    new_master_key = Fernet.generate_key()
    keystore.rotate_master_key(db_session, new_master_key)
    monkeypatch.setattr(config.settings, "keystore_master_key", new_master_key.decode())

    # After rotation, rotated_at should be set
    row_after = db_session.get(KeystoreKey, "rotation-test")
    assert row_after.rotated_at is not None


def test_delete_key_removes_row_and_next_call_generates_new_key(db_session):
    original_key = keystore.get_or_create_key(db_session, "to-delete")
    keystore.delete_key(db_session, "to-delete")
    new_key = keystore.get_or_create_key(db_session, "to-delete")
    assert new_key != original_key
