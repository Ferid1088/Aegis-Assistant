from sqlalchemy import text
from sqlalchemy.orm import Session

from rag.migrations.base import Migration


def get_current_version(db: Session, store_name: str) -> int:
    row = db.execute(
        text("SELECT version FROM store_schema_versions WHERE store_name = :name"),
        {"name": store_name},
    ).fetchone()
    return row[0] if row is not None else 0


def _record_version(db: Session, store_name: str, version: int) -> None:
    # CURRENT_TIMESTAMP (not the Postgres-only now()) is used here because this raw SQL
    # also runs against the in-memory SQLite `db_session` test fixture, which has no
    # `now()` function; CURRENT_TIMESTAMP is ANSI SQL and both dialects support it.
    db.execute(
        text("""
            INSERT INTO store_schema_versions (store_name, version)
            VALUES (:name, :version)
            ON CONFLICT (store_name) DO UPDATE SET version = :version, applied_at = CURRENT_TIMESTAMP
        """),
        {"name": store_name, "version": version},
    )
    db.commit()


def apply_pending(
    db: Session, store: object, store_name: str, migrations: list[Migration],
) -> list[int]:
    current = get_current_version(db, store_name)
    pending = sorted((m for m in migrations if m.version > current), key=lambda m: m.version)

    applied: list[int] = []
    for migration in pending:
        migration.apply(store)
        _record_version(db, store_name, migration.version)
        applied.append(migration.version)
    return applied
