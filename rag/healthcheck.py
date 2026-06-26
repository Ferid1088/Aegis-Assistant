from rag.config import settings
from rag.llm.provider import get_llm, get_embedder, get_device


def main():
    print(f"Device: {get_device()}")

    emb = get_embedder()
    dim = len(list(emb.embed(["test"]))[0])
    assert dim == 1024, f"bge-m3 should be 1024-dim, was {dim}"
    print(f"✅ Embedder OK (dim={dim})")

    llm = get_llm()
    r = llm.invoke("Reply with only: OK")
    print(f"✅ LLM OK ({settings.llm_backend}: {r.content[:20]})")

    from rag.storage.vector_store import QdrantVectorStore
    QdrantVectorStore().ensure_collection(dense_dim=dim)
    print("✅ Qdrant OK")

    from rag.storage.document_store import SQLiteDocumentStore
    SQLiteDocumentStore()
    print("✅ SQLite OK")

    print("\n🎉 Foundation stands.")


if __name__ == "__main__":
    main()
