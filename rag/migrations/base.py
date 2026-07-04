from typing import Protocol, runtime_checkable


@runtime_checkable
class Migration(Protocol):
    """One versioned, forward-only change to a non-Postgres store's schema.

    `apply()` MUST be idempotent: calling it again on a store already at or
    past `version` must be safe and a no-op in effect. The runner only calls
    each migration once per run, but idempotency is required so a migration
    can also be re-applied manually during incident recovery without first
    checking version state by hand.

    Schema-ownership convention (binds every migration from 0002 onward):
    runtime auto-ensure (`QdrantVectorStore.ensure_collection`,
    `Neo4jGraphStore._ensure_indexes`) is the single source of truth for what
    a FRESH install looks like and is never modified by this framework. A
    real schema change requires updating BOTH: (1) the relevant auto-ensure
    method, so a fresh install lands on the new state directly, and (2) a new
    numbered migration here, so an already-deployed store is transformed from
    the previous version to the new one. Only the `0001_baseline` migrations
    are exempt from part (2), since they exist to register the pre-existing
    state as version 1, not to transform anything.
    """

    version: int

    def apply(self, store: object) -> None: ...
