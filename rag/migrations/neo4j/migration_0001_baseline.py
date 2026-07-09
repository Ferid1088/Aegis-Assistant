"""Registers today's already-correct Neo4j index setup as version 1.

Delegates to the existing, idempotent Neo4jGraphStore._ensure_indexes — this is
the only migration allowed to just call the runtime auto-ensure method, since
it's establishing pre-existing state as a baseline rather than transforming
anything (see rag.migrations.base.Migration's docstring).
"""


class Migration0001:
    version = 1

    def apply(self, store: object) -> None:
        store._ensure_indexes()


MIGRATION = Migration0001()
