from unittest.mock import patch


@patch("sentry_sdk.init")
def test_create_app_initializes_sentry_when_dsn_is_set(mock_sentry_init, monkeypatch):
    from rag.api.main import create_app
    from rag.config import settings

    monkeypatch.setattr(settings, "glitchtip_dsn", "https://fake-key@glitchtip.local/1")

    create_app()

    mock_sentry_init.assert_called_once()
    assert mock_sentry_init.call_args.kwargs["dsn"] == "https://fake-key@glitchtip.local/1"


@patch("sentry_sdk.init")
def test_create_app_skips_sentry_when_dsn_is_empty(mock_sentry_init, monkeypatch):
    from rag.api.main import create_app
    from rag.config import settings

    monkeypatch.setattr(settings, "glitchtip_dsn", "")

    create_app()

    mock_sentry_init.assert_not_called()
