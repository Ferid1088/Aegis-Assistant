from typing import Protocol

from rag.migrations.base import Migration


def test_migration_protocol_shape():
    class FakeMigration:
        version = 1
        def apply(self, store: object) -> None:
            pass

    m: Migration = FakeMigration()
    assert m.version == 1
    assert isinstance(Migration, type(Protocol))
