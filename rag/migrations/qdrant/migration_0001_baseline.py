"""Registers today's already-correct Qdrant collection setup as version 1.

Delegates to the existing, idempotent QdrantVectorStore.ensure_collection — this
is the only migration allowed to just call the runtime auto-ensure method, since
it's establishing pre-existing state as a baseline rather than transforming
anything (see rag.migrations.base.Migration's docstring).
"""


class Migration0001:
    version = 1

    def apply(self, store: object) -> None:
        store.ensure_collection(dense_dim=1024)


MIGRATION = Migration0001()
