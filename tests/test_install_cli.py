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
    try:
        mock_session_local.return_value = MagicMock()
        mock_ensure_admin.return_value = None
        mock_read_env_value.return_value = "freshly-generated-secret"

        import install
        install.run_install()

        # Both NEO4J_PASSWORD and QDRANT_URL must be re-read from the .env file
        # install.py just wrote, and used to update the already-constructed
        # `settings` singleton -- otherwise run_store_migrate.main() and
        # healthcheck_main() (called later in this same process) would silently
        # keep using settings' stale import-time defaults (embedded-mode Qdrant,
        # in the QDRANT_URL case) for this entire run.
        assert mock_read_env_value.call_count == 2
        assert call(Path(".env"), "NEO4J_PASSWORD") in mock_read_env_value.call_args_list
        assert call(Path(".env"), "QDRANT_URL") in mock_read_env_value.call_args_list
        assert settings.neo4j_password == "freshly-generated-secret"
        assert settings.qdrant_url == "freshly-generated-secret"
    finally:
        settings.neo4j_password = original_neo4j_password
        settings.qdrant_url = original_qdrant_url


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
