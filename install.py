"""Installer: takes a fresh Docker-equipped machine to a running, migrated appliance
with a first admin account. Every step is idempotent -- re-running this script never
regenerates an existing secret, never creates a second admin, and never fails merely
because a prior run already completed that step.
"""

import subprocess
from pathlib import Path

from rag.bootstrap.env_writer import read_env_value, write_missing_env_vars
from rag.bootstrap.first_admin import ensure_first_admin
from rag.bootstrap.glitchtip_db import ensure_glitchtip_database
from rag.bootstrap.prereqs import check_docker, check_gpu, check_ram
from rag.bootstrap.secrets_gen import (
    generate_glitchtip_secret_key, generate_grafana_admin_password, generate_jwt_secret, generate_keystore_master_key,
    generate_neo4j_password, generate_postgres_password,
)
from rag.bootstrap.tls_cert import ensure_tls_certificate
from rag.bootstrap.wait_for_postgres import wait_for_postgres_ready
from rag.config import settings
from rag.healthcheck import main as healthcheck_main
from rag.infra.stores.sql.base import SessionLocal, reset_engine

import run_store_migrate


def run_install() -> None:
    print("== Checking prerequisites ==")
    check_docker()
    check_ram()
    has_gpu = check_gpu()

    print("== Generating TLS certificate ==")
    ensure_tls_certificate()

    print("== Generating secrets ==")
    env_path = Path(".env")
    env_vars = {
        "JWT_SECRET_KEY": generate_jwt_secret(),
        "KEYSTORE_MASTER_KEY": generate_keystore_master_key(),
        # Consumed by docker-compose.yml's postgres/pgbouncer/app/worker services
        # (interpolated via ${POSTGRES_PASSWORD:-password}) and, in-process, by
        # the database_url resync below (Phase 8.10b). Only takes effect against
        # a genuinely fresh Postgres data volume -- Postgres (like Neo4j) applies
        # POSTGRES_PASSWORD only during its first-ever initdb on an empty volume.
        "POSTGRES_PASSWORD": generate_postgres_password(),
        "NEO4J_PASSWORD": generate_neo4j_password(),
        # Host-reachable (via redis's new loopback-published port) -- host-side
        # steps in this same process (healthcheck_main()'s check_redis()) need
        # this, same host-vs-container split as QDRANT_URL below. The
        # container-internal override lives in docker-compose.yml's app/worker
        # environment: blocks.
        "REDIS_URL": "redis://localhost:6379",
        "QDRANT_URL": "http://localhost:6333",
        "GLITCHTIP_SECRET_KEY": generate_glitchtip_secret_key(),
        "GRAFANA_ADMIN_PASSWORD": generate_grafana_admin_password(),
        # Phase 8.10c: GPU detected at install time -> vLLM (continuous batching,
        # the doc's production tier); no GPU -> Ollama (CPU-friendly, matches
        # rag/config.py's own bare-Settings() default). Only written once, on
        # first install -- re-running install.py never overwrites an operator's
        # own LLM_BACKEND choice already sitting in .env.
        "LLM_BACKEND": "vllm" if has_gpu else "ollama",
        "VLLM_BASE_URL": "http://localhost:8000/v1",
    }
    if has_gpu:
        # vLLM (and the underlying HuggingFace loader) needs a HuggingFace repo
        # id, not Ollama's registry-tag form -- rag/config.py's own
        # llm_model class-level default ("qwen2.5:7b") is Ollama-format and is
        # deliberately left untouched for the no-GPU/Ollama path. Only written
        # once, on first install, same as LLM_BACKEND above: re-running
        # install.py never overwrites an operator's own LLM_MODEL choice
        # already sitting in .env.
        env_vars["LLM_MODEL"] = "Qwen/Qwen2.5-7B-Instruct"
    written = write_missing_env_vars(env_path, env_vars)
    if written:
        print(f"Generated: {', '.join(written)}")
    else:
        print("All secrets already present, nothing generated.")

    # Sync the in-process settings singleton with whatever NEO4J_PASSWORD actually
    # ended up in .env (freshly generated above, or already present from a prior
    # run) -- `settings` was constructed at module import time, before this run's
    # secrets existed, so without this it would still hold the stale default while
    # the Neo4j container (created fresh from this same .env, next step) uses the
    # real value.
    settings.neo4j_password = read_env_value(env_path, "NEO4J_PASSWORD") or settings.neo4j_password
    # Same class of bug, same fix: `settings` was constructed at import time with
    # qdrant_url=="" (the embedded-mode default) -- on a fresh install, QDRANT_URL
    # doesn't exist in .env until write_missing_env_vars() writes it a few lines
    # above, so without this, run_store_migrate.main() and healthcheck_main() below
    # would silently run against embedded Qdrant (./data/qdrant via QdrantClient(path=...))
    # instead of the real `qdrant` server container this whole sub-phase stands up.
    settings.qdrant_url = read_env_value(env_path, "QDRANT_URL") or settings.qdrant_url
    # Same class of bug as neo4j_password/qdrant_url above: settings.llm_backend
    # was constructed at import time with the stale "ollama" default -- on a
    # fresh GPU install, LLM_BACKEND=vllm doesn't exist in .env until
    # write_missing_env_vars() writes it a few lines above. Without this,
    # healthcheck_main()'s get_llm() call below would silently keep trying
    # Ollama even though this install generated a vLLM-targeted LLM_BACKEND.
    settings.llm_backend = read_env_value(env_path, "LLM_BACKEND") or settings.llm_backend
    # Same class of bug, same fix, paired with llm_backend directly above:
    # settings.llm_model was constructed at import time with the stale
    # "qwen2.5:7b" (Ollama-tag) default -- on a fresh GPU install, LLM_MODEL
    # doesn't exist in .env until write_missing_env_vars() writes it a few
    # lines above. Without this, healthcheck_main()'s get_llm() call below
    # would build ChatOpenAI(model="qwen2.5:7b", base_url=vllm...) even though
    # vLLM was started with --model Qwen/Qwen2.5-7B-Instruct, so the request
    # would be rejected as an unknown model.
    settings.llm_model = read_env_value(env_path, "LLM_MODEL") or settings.llm_model
    # Same class of bug as neo4j_password/qdrant_url above: settings.redis_url
    # was constructed at import time with the "" default -- on a fresh
    # install, REDIS_URL doesn't exist in .env until write_missing_env_vars()
    # writes it a few lines above. Without this, healthcheck_main()'s
    # check_redis() call below would find settings.redis_url == "" -> get_redis()
    # returns None -> raise, failing every fresh install's final healthcheck
    # step even though Redis is actually running fine.
    settings.redis_url = read_env_value(env_path, "REDIS_URL") or settings.redis_url
    # Same class of bug as neo4j_password/qdrant_url above, but database_url
    # can't use the same `or` passthrough idiom directly -- POSTGRES_PASSWORD
    # is only the password component, not the full connection string. Rebuild
    # it here so run_store_migrate.main()/first-admin creation/healthcheck_main()
    # below (all later in this same process) use the real generated password
    # instead of the stale import-time dev-default. reset_engine() clears
    # rag/infra/stores/sql/base.py's cached engine so the next SessionLocal() call
    # picks up the rebuilt URL (Phase 8.10b).
    postgres_password = read_env_value(env_path, "POSTGRES_PASSWORD")
    if postgres_password:
        settings.database_url = f"postgresql+psycopg://postgres:{postgres_password}@localhost:5432/appliance"
        reset_engine()

    print("== Starting services ==")
    # Must exist before `docker compose up` touches it: on Linux, dockerd (running
    # as root) auto-creates missing bind-mount host directories -- if `./data`
    # itself doesn't exist yet, it gets created root-owned, and every host-side
    # write under it (SQLite document store, Qdrant, uploads) then fails with
    # "unable to open database file" for the unprivileged user running this
    # script. Creating it first as that user keeps ownership sane; the
    # postgres/neo4j/redis subdirectories Docker still creates underneath it are
    # fine root-owned since no host-side code writes into those directly.
    Path("data").mkdir(exist_ok=True)
    # docker-compose.yml's vllm service is profiles: ["gpu"] -- Compose excludes
    # a profile-gated service from a plain `docker compose up -d` unless
    # `--profile gpu` is passed. Without this, a GPU install would write
    # LLM_BACKEND=vllm above and then never actually start the vllm container,
    # so the healthcheck step below would fail trying to reach it. No-GPU path
    # is unchanged: no profile flag, same argv as before.
    compose_up_cmd = ["docker", "compose"]
    if has_gpu:
        compose_up_cmd += ["--profile", "gpu"]
    compose_up_cmd += ["up", "-d"]
    subprocess.run(compose_up_cmd, check=True)

    # `up -d` returns once containers are started, not once postgres has finished
    # its first-run initdb bootstrap -- wait for it before anything execs into it.
    wait_for_postgres_ready()

    ensure_glitchtip_database()

    print("== Running migrations ==")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    run_store_migrate.main()

    print("== Creating first admin ==")
    db = SessionLocal()
    try:
        result = ensure_first_admin(db)
    finally:
        db.close()

    if result is not None:
        username, password = result
        print("=" * 60)
        print("SAVE THIS NOW -- it will not be shown again:")
        print(f"  username: {username}")
        print(f"  password: {password}")
        print("=" * 60)
    else:
        print("Admin account already exists, skipping.")

    print("== Verifying health ==")
    # A fresh vLLM install may still be downloading/loading its model here and
    # fail this healthcheck through no fault of the install itself -- set
    # SKIP_LLM_HEALTHCHECK=true (rag/config.py) to bypass the LLM check alone.
    healthcheck_main()

    print("\n🎉 Install complete.")


if __name__ == "__main__":
    run_install()
