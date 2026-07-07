from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    observability_db_path: str = "./data/observability.db"

    llm_backend: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "qwen2.5:7b"
    extraction_model: str = "qwen2.5:7b"

    # Global in-flight generation cap (Phase 8.10c) -- the shared LLM
    # backend's total concurrent-generation ceiling (source doc: "~10-25
    # concurrent generations" for one 24GB-GPU qwen2.5:7b instance). Tune
    # to your actual hardware; this is a GLOBAL cap, not a per-user limit.
    max_inflight_generations: int = 20

    # Per-request timeout for the LLM generation call itself (both the
    # vLLM and Ollama backends) -- a hung backend now fails cleanly
    # instead of holding a FastAPI worker thread forever (Phase 8.10c).
    llm_request_timeout_seconds: int = 60

    # Lets install.py/update.py's post-bootstrap healthcheck skip the LLM round-trip --
    # for CI jobs that intentionally don't set up Ollama/vLLM (that stack is heavy and
    # only the eval/upload-and-chat job needs it), a stack with no LLM backend running
    # is still "genuinely up" for every other purpose install.py verifies.
    skip_llm_healthcheck: bool = False

    device: str = ""

    dense_embedding_model: str = "BAAI/bge-m3"
    sparse_embedding_model: str = "Qdrant/bm25"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    qdrant_path: str = "./data/qdrant"
    qdrant_collection: str = "documents"
    # Server mode — empty = embedded (QdrantClient(path=...), today's only
    # behavior); set (e.g. "http://qdrant:6333" inside containers, or
    # "http://localhost:6333" on the host) = QdrantClient(url=...). Written
    # into .env by install.py for every fresh install (Phase 8.10a);
    # deliberately empty by default so tests/eval scripts/CI without a
    # populated .env keep using embedded mode unchanged.
    qdrant_url: str = ""
    sqlite_path: str = "./data/documents.db"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 100 * 1024 * 1024  # 100 MB
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

    # Mandatory for any real (install.py-run) deployment — enforced via
    # check_redis() in /readyz and the install-time healthcheck (Phase
    # 8.10b). Stays "" here only so bare Settings() (unit tests, eval
    # scripts, CI without a populated .env) keeps working unchanged; every
    # real install already gets a concrete REDIS_URL written to .env.
    redis_url: str = ""
    cache_ttl_transform: int = 3600    # 1 h
    cache_ttl_embed: int = 86400       # 24 h
    cache_ttl_answer: int = 900        # 15 min

    # GlitchTip (self-hosted, Sentry-compatible error tracking) -- empty = disabled,
    # matching redis_url's convention
    glitchtip_dsn: str = ""

    # Version filter — activate AFTER re-indexing with is_current in payload
    version_filter: bool = False

    # HyDE
    hyde_threshold: float = 0.3
    hyde_enabled: bool = False

    # Reranker tuning
    reranker_use_fp16: bool = False
    reranker_batch_size: int = 32

    # Durable checkpointer — set to e.g. "./data/checkpoints.db" to persist across restarts
    checkpoint_db_path: str = ""

    # Asymmetric embedding prefixes (empty = no prefix, i.e. bge-m3 default)
    dense_query_prefix: str = ""
    dense_passage_prefix: str = ""   # applied to texts during ingestion for asymmetric models

    # Postgres (users/RBAC/sessions) — dev-only default; §7 replaces with a generated secret
    database_url: str = "postgresql+psycopg://postgres:password@localhost:5432/appliance"

    # JWT — dev-only fixed key; §7 replaces with an installer-generated secret
    jwt_secret_key: str = "yhzI7e9m4LMmV2bUpZuUFjg7I6WgTooqMBN-6ZiXxDA_PwMg_Xb1sDHpTPIUMX2f"
    jwt_access_ttl_seconds: int = 900        # 15 min
    jwt_refresh_ttl_seconds: int = 1209600   # 14 days
    jwt_mfa_pending_ttl_seconds: int = 300   # 5 min

    # MFA secret-at-rest encryption — dev-only fixed key; §7 replaces with a keystore-managed key
    mfa_encryption_key: str = "uhlp2Qq9mxc53yfrtlcGqejIbw0ZB7yWPJRbY3gtNmo="

    # Keystore master key — wraps all per-purpose DEKs (rag/crosscutting/security/keystore.py).
    # dev-only fixed key; §7 replaces with an installer-generated secret (see generate_secrets.py)
    keystore_master_key: str = "17EHdjDj-yCVoqEW8QlY6DSRA9yiz1F4LfwnRKu51ls="

    # Account lockout
    lockout_threshold: int = 5
    lockout_duration_seconds: int = 900      # 15 min

    # Audit log directory (existing AuditLog, extended with auth/RBAC events)
    audit_log_dir: str = "data/audit"

    backup_retention_count: int = 7


settings = Settings()
