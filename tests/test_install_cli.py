from unittest.mock import MagicMock, patch


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
    mock_run_store_migrate.main.assert_called_once()
    mock_ensure_admin.assert_called_once()
    mock_healthcheck.assert_called_once()


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
    mock_subprocess_run, mock_run_store_migrate, mock_session_local, mock_ensure_admin, mock_healthcheck, capsys,
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None  # admin already existed

    import install
    install.run_install()

    captured = capsys.readouterr()
    assert "SAVE THIS NOW" not in captured.out


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
):
    mock_session_local.return_value = MagicMock()
    mock_ensure_admin.return_value = None

    import install
    install.run_install()

    written_values = mock_write_env.call_args.args[1]
    assert "REDIS_URL" in written_values
