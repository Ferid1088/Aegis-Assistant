from pathlib import Path
from unittest.mock import MagicMock, call, patch


@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_calls_all_steps_in_order(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres,
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = ("admin", "generated-password")

    import install
    install.run_install()

    mock_check_docker.assert_called_once()
    mock_check_ram.assert_called_once()
    mock_check_gpu.assert_called_once()
    mock_write_env.assert_called_once()
    assert mock_subprocess_run.call_count >= 2  # docker compose up -d, alembic upgrade head (run_store_migrate is a direct call, not subprocess)
    mock_wait_for_postgres.assert_called_once()
    mock_run_store_migrate.main.assert_called_once()
    mock_ensure_admin.assert_called_once()
    mock_healthcheck.assert_called_once()


@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_prints_credentials_only_when_admin_created(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, capsys,
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None  # admin already existed

    import install
    install.run_install()

    captured = capsys.readouterr()
    assert "SAVE THIS NOW" not in captured.out


@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_writes_redis_url(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres,
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert "REDIS_URL" in written_values


@patch("install.read_env_value")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_syncs_in_process_neo4j_password_and_qdrant_url_from_env(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin,
    mock_healthcheck, mock_wait_for_postgres, mock_read_env_value,
):
    from rag.config import settings
    original_neo4j_password = settings.neo4j_password
    original_qdrant_url = settings.qdrant_url
    # mock_read_env_value.return_value applies to every read_env_value() call
    # install.run_install() makes -- since Phase 8.10b, that now also includes
    # a POSTGRES_PASSWORD read that rebuilds settings.database_url (reset_engine
    # isn't mocked here, so the real one runs too, harmlessly), a REDIS_URL
    # read that resyncs settings.redis_url (fixing a real bug: install.py's
    # host-side healthcheck_main() couldn't resolve the "redis" hostname, since
    # settings.redis_url started at the "" default and was never resynced), and
    # (Phase 8.10c) an LLM_BACKEND read that resyncs settings.llm_backend, and
    # (Phase 8.10c re-review) an LLM_MODEL read that resyncs settings.llm_model
    # -- mock_check_gpu is unset here, so the default MagicMock() return value
    # is truthy and the has_gpu branch (which includes the LLM_MODEL read) runs.
    # Save/restore all of them so this test doesn't leak a bogus value into
    # later tests' shared `settings` singleton.
    original_database_url = settings.database_url
    original_redis_url = settings.redis_url
    original_llm_backend = settings.llm_backend
    original_llm_model = settings.llm_model
    try:
        mock_session_local.return_value = MagicMock()
        mock_ensure_admin.return_value = None
        mock_read_env_value.return_value = "freshly-generated-secret"

        import install
        install.run_install()

        # NEO4J_PASSWORD, QDRANT_URL, POSTGRES_PASSWORD, REDIS_URL,
        # LLM_BACKEND, and LLM_MODEL must all be re-read from the .env file
        # install.py just wrote, and used to update the already-constructed
        # `settings` singleton -- otherwise run_store_migrate.main() and
        # healthcheck_main() (called later in this same process) would
        # silently keep using settings' stale import-time defaults
        # (embedded-mode Qdrant, in the QDRANT_URL case; no Redis at all, in
        # the REDIS_URL case; the "ollama" default, in the LLM_BACKEND case;
        # the Ollama-tag "qwen2.5:7b" default, in the LLM_MODEL case) for this
        # entire run.
        assert mock_read_env_value.call_count == 6
        assert call(Path(".env"), "NEO4J_PASSWORD") in mock_read_env_value.call_args_list
        assert call(Path(".env"), "QDRANT_URL") in mock_read_env_value.call_args_list
        assert call(Path(".env"), "REDIS_URL") in mock_read_env_value.call_args_list
        assert call(Path(".env"), "POSTGRES_PASSWORD") in mock_read_env_value.call_args_list
        assert call(Path(".env"), "LLM_BACKEND") in mock_read_env_value.call_args_list
        assert call(Path(".env"), "LLM_MODEL") in mock_read_env_value.call_args_list
        assert settings.neo4j_password == "freshly-generated-secret"
        assert settings.qdrant_url == "freshly-generated-secret"
        assert settings.redis_url == "freshly-generated-secret"
        assert settings.llm_backend == "freshly-generated-secret"
        assert settings.llm_model == "freshly-generated-secret"
    finally:
        settings.neo4j_password = original_neo4j_password
        settings.qdrant_url = original_qdrant_url
        settings.database_url = original_database_url
        settings.redis_url = original_redis_url
        settings.llm_backend = original_llm_backend
        settings.llm_model = original_llm_model


@patch("install.check_gpu")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_writes_llm_backend_vllm_when_gpu_detected(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, mock_check_gpu,
):
    mock_check_gpu.return_value = True
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert written_values["LLM_BACKEND"] == "vllm"


@patch("install.check_gpu")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_writes_llm_backend_ollama_when_no_gpu(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, mock_check_gpu,
):
    mock_check_gpu.return_value = False
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert written_values["LLM_BACKEND"] == "ollama"


@patch("install.reset_engine")
@patch("install.check_gpu")
@patch("install.read_env_value")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_syncs_in_process_llm_backend_from_env(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin,
    mock_healthcheck, mock_wait_for_postgres, mock_read_env_value, mock_check_gpu, mock_reset_engine,
):
    from rag.config import settings
    original_llm_backend = settings.llm_backend
    original_llm_model = settings.llm_model
    original_neo4j_password = settings.neo4j_password
    original_qdrant_url = settings.qdrant_url
    original_database_url = settings.database_url
    original_redis_url = settings.redis_url
    try:
        mock_check_gpu.return_value = True
        mock_session_local.return_value = MagicMock()
        mock_ensure_admin.return_value = None
        mock_read_env_value.return_value = "vllm"

        import install
        install.run_install()

        # LLM_BACKEND must be re-read from the .env file install.py just wrote
        # and used to update the already-constructed `settings` singleton --
        # otherwise healthcheck_main()'s get_llm() call (later in this same
        # process) would silently keep using settings' stale import-time
        # default ("ollama") even on a fresh GPU install that generated
        # LLM_BACKEND=vllm.
        assert settings.llm_backend == "vllm"
    finally:
        settings.llm_backend = original_llm_backend
        settings.llm_model = original_llm_model
        settings.neo4j_password = original_neo4j_password
        settings.qdrant_url = original_qdrant_url
        settings.database_url = original_database_url
        settings.redis_url = original_redis_url


@patch("install.reset_engine")
@patch("install.check_gpu")
@patch("install.read_env_value")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_syncs_in_process_llm_model_from_env(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin,
    mock_healthcheck, mock_wait_for_postgres, mock_read_env_value, mock_check_gpu, mock_reset_engine,
):
    from rag.config import settings
    original_llm_model = settings.llm_model
    original_llm_backend = settings.llm_backend
    original_neo4j_password = settings.neo4j_password
    original_qdrant_url = settings.qdrant_url
    original_database_url = settings.database_url
    original_redis_url = settings.redis_url
    try:
        mock_check_gpu.return_value = True
        mock_session_local.return_value = MagicMock()
        mock_ensure_admin.return_value = None
        mock_read_env_value.return_value = "Qwen/Qwen2.5-7B-Instruct"

        import install
        install.run_install()

        # LLM_MODEL must be re-read from the .env file install.py just wrote
        # and used to update the already-constructed `settings` singleton --
        # otherwise healthcheck_main()'s get_llm() call (later in this same
        # process) would silently keep using settings' stale import-time
        # default ("qwen2.5:7b", Ollama-tag format) even on a fresh GPU
        # install that generated LLM_MODEL=Qwen/Qwen2.5-7B-Instruct, causing
        # vLLM to reject the request as an unknown model.
        assert settings.llm_model == "Qwen/Qwen2.5-7B-Instruct"
    finally:
        settings.llm_model = original_llm_model
        settings.llm_backend = original_llm_backend
        settings.neo4j_password = original_neo4j_password
        settings.qdrant_url = original_qdrant_url
        settings.database_url = original_database_url
        settings.redis_url = original_redis_url


@patch("install.reset_engine")
@patch("install.read_env_value")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_syncs_in_process_database_url_from_generated_postgres_password(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin,
    mock_healthcheck, mock_wait_for_postgres, mock_read_env_value, mock_reset_engine,
):
    from rag.config import settings
    original_database_url = settings.database_url
    # mock_read_env_value.return_value applies to *every* read_env_value() call
    # install.run_install() makes, not just the POSTGRES_PASSWORD one this test
    # cares about -- so it also flows into settings.neo4j_password/qdrant_url/
    # redis_url/llm_backend via the other resync lines. Save/restore those
    # too, or this test would leak "freshly-generated-postgres-secret" into
    # later tests' shared `settings` singleton (e.g. a subsequent real
    # Qdrant-hitting test would try to connect to a host literally named
    # "freshly-generated-postgres-secret"). mock_check_gpu is unset here, so
    # the default MagicMock() return value is truthy and the has_gpu branch
    # (which includes the LLM_MODEL read/resync) also runs.
    original_neo4j_password = settings.neo4j_password
    original_qdrant_url = settings.qdrant_url
    original_redis_url = settings.redis_url
    original_llm_backend = settings.llm_backend
    original_llm_model = settings.llm_model
    try:
        mock_session_local.return_value = MagicMock()
        mock_ensure_admin.return_value = None
        mock_read_env_value.return_value = "freshly-generated-postgres-secret"

        import install
        install.run_install()

        # database_url must be rebuilt using the real generated POSTGRES_PASSWORD
        # (not the stale import-time dev-default), and reset_engine() must be
        # called so rag/infra/stores/sql/base.py's cached engine picks it up --
        # otherwise run_store_migrate.main()/first-admin creation/healthcheck_main()
        # (all later in this same process) would silently keep using the stale
        # password.
        assert settings.database_url == (
            "postgresql+psycopg://postgres:freshly-generated-postgres-secret@localhost:5432/appliance"
        )
        mock_reset_engine.assert_called_once()
    finally:
        settings.database_url = original_database_url
        settings.neo4j_password = original_neo4j_password
        settings.qdrant_url = original_qdrant_url
        settings.redis_url = original_redis_url
        settings.llm_backend = original_llm_backend
        settings.llm_model = original_llm_model


@patch("install.ensure_glitchtip_database")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_creates_glitchtip_database_and_writes_its_secret(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin,
    mock_healthcheck, mock_wait_for_postgres, mock_ensure_glitchtip_db,
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    mock_ensure_glitchtip_db.assert_called_once()
    written_values = mock_write_env.call_args.args[1]
    assert "GLITCHTIP_SECRET_KEY" in written_values


@patch("install.ensure_glitchtip_database")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_gpu")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_writes_grafana_admin_password(
    mock_check_docker, mock_check_ram, mock_check_gpu, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin,
    mock_healthcheck, mock_wait_for_postgres, mock_ensure_glitchtip_db,
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert "GRAFANA_ADMIN_PASSWORD" in written_values


@patch("install.check_gpu")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_docker_compose_up_includes_gpu_profile_when_gpu_detected(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, mock_check_gpu,
):
    # Final-review Finding 1: docker-compose.yml's vllm service is
    # profiles: ["gpu"] -- Compose silently excludes it from a plain
    # `docker compose up -d`. On a GPU install (LLM_BACKEND=vllm written
    # above), the `docker compose up -d` call itself must include
    # `--profile gpu`, or vllm never starts and the healthcheck step later
    # in this same run fails trying to reach it.
    mock_check_gpu.return_value = True
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    compose_up_calls = [
        c for c in mock_subprocess_run.call_args_list
        if c.args[0][-2:] == ["up", "-d"]
    ]
    assert len(compose_up_calls) == 1
    argv = compose_up_calls[0].args[0]
    assert argv == ["docker", "compose", "--profile", "gpu", "up", "-d"]


@patch("install.check_gpu")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_docker_compose_up_unchanged_when_no_gpu(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, mock_check_gpu,
):
    # Non-GPU path must be provably unchanged: no --profile flag, exact same
    # argv as before this fix.
    mock_check_gpu.return_value = False
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    compose_up_calls = [
        c for c in mock_subprocess_run.call_args_list
        if c.args[0][-2:] == ["up", "-d"]
    ]
    assert len(compose_up_calls) == 1
    argv = compose_up_calls[0].args[0]
    assert argv == ["docker", "compose", "up", "-d"]
    assert "--profile" not in argv
    assert "gpu" not in argv


@patch("install.check_gpu")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_writes_hf_format_llm_model_when_gpu_detected(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, mock_check_gpu,
):
    # Final-review Finding 2: "qwen2.5:7b" (rag/config.py's Ollama-format
    # default) is not a valid vLLM/HuggingFace repo id -- a GPU install must
    # also write an HF-format LLM_MODEL default so vllm's container command
    # (docker-compose.yml: ${LLM_MODEL:-qwen2.5:7b}) can actually load a model.
    mock_check_gpu.return_value = True
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert written_values["LLM_MODEL"] == "Qwen/Qwen2.5-7B-Instruct"


@patch("install.check_gpu")
@patch("install.wait_for_postgres_ready")
@patch("install.healthcheck_main")
@patch("install.ensure_first_admin")
@patch("install.SessionLocal")
@patch("install.run_store_migrate")
@patch("install.subprocess.run")
@patch("install.write_missing_env_vars")
@patch("install.check_ram")
@patch("install.check_docker")
def test_run_install_does_not_write_llm_model_when_no_gpu(
    mock_check_docker, mock_check_ram, mock_write_env,
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck,
    mock_wait_for_postgres, mock_check_gpu,
):
    # Non-GPU path must be provably unchanged: no LLM_MODEL key written at
    # all, leaving rag/config.py's own "qwen2.5:7b" class-level default (an
    # Ollama-format tag, correct for Ollama) in effect untouched.
    mock_check_gpu.return_value = False
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert "LLM_MODEL" not in written_values
