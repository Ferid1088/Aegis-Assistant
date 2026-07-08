from sqlalchemy import text

from rag.capabilities.cache import get_redis
from rag.config import settings
from rag.llm.provider import get_llm, get_embedder, get_device
from rag.infra.stores.sql.base import SessionLocal


def check_postgres() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()


def check_redis() -> None:
    r = get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable")
    # get_redis() caches its client forever once a connection has ever
    # succeeded (rag/capabilities/cache.py) -- it does NOT re-check liveness
    # on later calls. Without this .ping(), a Redis outage that happens
    # after the first successful connection would never be detected here.
    r.ping()


def main():
    print(f"Device: {get_device()}")

    emb = get_embedder()
    dim = len(list(emb.embed(["test"]))[0])
    assert dim == 1024, f"bge-m3 should be 1024-dim, was {dim}"
    print(f"✅ Embedder OK (dim={dim})")

    if settings.skip_llm_healthcheck:
        print("⏭️  LLM check skipped (SKIP_LLM_HEALTHCHECK set)")
    else:
        llm = get_llm()
        r = llm.invoke("Reply with only: OK")
        print(f"✅ LLM OK ({settings.llm_backend}: {r.content[:20]})")

    from rag.infra.stores.vector_store import QdrantVectorStore
    QdrantVectorStore().ensure_collection(dense_dim=dim)
    print("✅ Qdrant OK")

    from rag.infra.stores.document_store import SQLiteDocumentStore
    SQLiteDocumentStore()
    print("✅ SQLite OK")

    check_postgres()
    print("✅ Postgres OK")

    check_redis()
    print("✅ Redis OK")

    print("\n🎉 Foundation stands.")


if __name__ == "__main__":
    main()
