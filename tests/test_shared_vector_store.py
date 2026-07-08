"""Regression tests for two real bugs found while verifying the `eval-harness`
CI job (Phase 8.8, Task 4) via `tests/integration/test_upload_and_chat_flow.py`:

1. rag/pipelines/ingestion/nodes.py (writes) and rag/graphs/query.py's SearchService
   (reads, via rag/capabilities/search/search_service.py) each used to lazily
   create and cache their OWN separate QdrantVectorStore. Embedded/local Qdrant
   storage (QdrantClient(path=...), used everywhere in this project -- there is
   no separate Qdrant server) takes an exclusive, portalocker-based lock on the
   storage directory for as long as any client stays open. That's fine as long
   as a single process only ever does ingestion OR querying -- but the moment
   one process does both (e.g. test_upload_and_chat_flow.py's Celery-eager
   upload-then-chat flow, deliberately single-process so no separate worker is
   needed), the second, independently-created client collides with the first,
   still-open one: RuntimeError("Storage folder ... is already accessed by
   another instance of Qdrant client..."). Fixed by routing both through one
   process-wide get_shared_vector_store() singleton (rag/infra/stores/vector_store.py).

2. Even after (1), the very first call to get_shared_vector_store() during a
   query could still race: rag/graphs/query.py's retrieval nodes (dense/sparse/
   graph) run concurrently across worker threads within a single query
   (LangGraph fans them out via a thread pool executor) -- a plain
   `if _shared_vec_store is None: _shared_vec_store = QdrantVectorStore()` is a
   classic check-then-set race with no synchronization: two threads can both
   see None and both try to open the exclusively-locked storage, and the loser
   raises RuntimeError instead of reusing the winner's client. Reproduced
   independently, non-deterministically, on a real local host run (not an
   act/CI-only artifact). Fixed with a real threading.Lock double-checked-lock.
"""
import threading
import time

import rag.infra.stores.vector_store as vector_store_module
from rag.infra.stores.vector_store import get_shared_vector_store


class _FakeClient:
    def close(self):
        pass


class _FakeVectorStore:
    """Stands in for QdrantVectorStore without touching real Qdrant storage.

    __init__ sleeps briefly to widen the race window: without that, the real
    QdrantClient(path=...) construction this stands in for does real
    (slower) I/O -- opening/parsing the storage directory -- which is exactly
    what gave the real race enough of a window to manifest in practice. A
    zero-cost fake constructor closes that window almost entirely under the
    GIL, which would make this test pass "by accident" even without the fix
    (confirmed while writing this test: 5/5 runs passed with the lock removed
    and no sleep here) -- the sleep restores a real, exercised race window so
    this test is a genuine, non-vacuous regression check.
    """

    instances_created = 0

    def __init__(self):
        time.sleep(0.05)
        _FakeVectorStore.instances_created += 1
        self.client = _FakeClient()


def _reset_module_singleton():
    vector_store_module._shared_vec_store = None
    _FakeVectorStore.instances_created = 0


def test_get_shared_vector_store_returns_same_instance(monkeypatch):
    _reset_module_singleton()
    monkeypatch.setattr(vector_store_module, "QdrantVectorStore", _FakeVectorStore)

    first = get_shared_vector_store()
    second = get_shared_vector_store()

    assert first is second
    assert _FakeVectorStore.instances_created == 1


def test_concurrent_first_calls_create_exactly_one_instance(monkeypatch):
    """Reproduces the real race: many threads calling get_shared_vector_store()
    for the very first time simultaneously (as LangGraph's concurrent
    dense/sparse/graph retrieval nodes do) must all resolve to the SAME single
    instance, not each open their own."""
    _reset_module_singleton()
    monkeypatch.setattr(vector_store_module, "QdrantVectorStore", _FakeVectorStore)

    n_threads = 32
    barrier = threading.Barrier(n_threads)
    results: list[object] = [None] * n_threads

    def worker(idx):
        barrier.wait()  # maximize the chance all threads hit the check at once
        results[idx] = get_shared_vector_store()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert _FakeVectorStore.instances_created == 1
    assert all(r is results[0] for r in results)


def test_close_shared_vector_store_resets_singleton(monkeypatch):
    _reset_module_singleton()
    monkeypatch.setattr(vector_store_module, "QdrantVectorStore", _FakeVectorStore)

    first = get_shared_vector_store()
    vector_store_module.close_shared_vector_store()
    second = get_shared_vector_store()

    assert first is not second
    assert _FakeVectorStore.instances_created == 2
