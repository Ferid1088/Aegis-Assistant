from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    observability_db_path: str = "./data/observability.db"

    llm_backend: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "qwen2.5:7b"
    extraction_model: str = "qwen2.5:7b"

    device: str = ""

    dense_embedding_model: str = "BAAI/bge-m3"
    sparse_embedding_model: str = "Qdrant/bm25"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    qdrant_path: str = "./data/qdrant"
    qdrant_collection: str = "documents"
    sqlite_path: str = "./data/documents.db"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    max_chunk_tokens: int = 512
    chunk_batch_size: int = 10
    enrich: bool = False
    build_graph: bool = False

    dense_top_k: int = 20
    sparse_top_k: int = 20
    graph_top_k: int = 20
    fusion_candidates: int = 40
    rerank_top_k: int = 10
    rrf_k: int = 60

    max_generation_tokens: int = 1024
    temperature: float = 0.1

    # ACL seam — master switch; stays False until 05.1 enforces it.
    acl_enforce: bool = False

    # Redis cache — off by default; set REDIS_URL=redis://localhost:6379 to enable
    redis_url: str = ""
    cache_ttl_transform: int = 3600    # 1 h
    cache_ttl_embed: int = 86400       # 24 h
    cache_ttl_answer: int = 900        # 15 min

    # Version filter — activate AFTER re-indexing with is_current in payload
    version_filter: bool = False

    # HyDE
    hyde_threshold: float = 0.3
    hyde_enabled: bool = False

    # Reranker tuning
    reranker_use_fp16: bool = False
    reranker_batch_size: int = 32


settings = Settings()
