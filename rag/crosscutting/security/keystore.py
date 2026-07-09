"""Envelope-encryption keystore — one master key wraps many per-purpose DEKs.

Rotation: rotate_master_key MUST be called with the OLD master key still
active in settings.keystore_master_key (so existing wrapped DEKs can be
unwrapped for re-wrapping under the new one). Only after rotate_master_key
returns successfully should the operator update the KEYSTORE_MASTER_KEY
env var to the new value. Doing this in the reverse order strands every
existing DEK unreadable — there is no recovery from unwrapping with the
wrong (already-replaced) master key.

None of this module's functions log raw key material (DEKs, the master
key, or wrapped bytes) — not in return values passed to logging, not in
exception messages.
"""

import secrets

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.config import settings
from rag.infra.stores.sql.models import KeystoreKey, _now


def _master_fernet(master_key: str | None = None) -> Fernet:
    return Fernet((master_key or settings.keystore_master_key).encode())


def get_or_create_key(db: Session, purpose: str) -> bytes:
    row = db.get(KeystoreKey, purpose)
    if row is not None:
        return _master_fernet().decrypt(row.wrapped_dek)

    dek = secrets.token_bytes(32)
    wrapped = _master_fernet().encrypt(dek)
    db.add(KeystoreKey(purpose=purpose, wrapped_dek=wrapped))
    db.commit()
    return dek


def rotate_master_key(db: Session, new_master_key: bytes) -> None:
    old_fernet = _master_fernet()
    new_fernet = _master_fernet(new_master_key.decode())

    rows = db.execute(select(KeystoreKey)).scalars().all()
    for row in rows:
        dek = old_fernet.decrypt(row.wrapped_dek)
        row.wrapped_dek = new_fernet.encrypt(dek)
        row.rotated_at = _now()
    db.commit()


def delete_key(db: Session, purpose: str) -> None:
    row = db.get(KeystoreKey, purpose)
    if row is not None:
        db.delete(row)
        db.commit()
