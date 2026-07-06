from unittest.mock import MagicMock, patch

from rag.crosscutting.security.rate_limit import user_or_ip_key


def test_user_or_ip_key_extracts_user_id_from_a_valid_token():
    request = MagicMock()
    request.headers = {"Authorization": "Bearer valid-token"}

    with patch("rag.crosscutting.security.rate_limit.decode_token") as mock_decode:
        mock_decode.return_value = {"sub": "user-abc-123", "type": "access"}
        key = user_or_ip_key(request)

    assert key == "user:user-abc-123"


def test_user_or_ip_key_falls_back_to_ip_when_no_token():
    request = MagicMock()
    request.headers = {}
    request.client.host = "203.0.113.5"

    key = user_or_ip_key(request)

    assert key == "ip:203.0.113.5"


def test_user_or_ip_key_falls_back_to_ip_on_invalid_token():
    request = MagicMock()
    request.headers = {"Authorization": "Bearer garbage-token"}
    request.client.host = "203.0.113.5"

    with patch("rag.crosscutting.security.rate_limit.decode_token", side_effect=Exception("bad token")):
        key = user_or_ip_key(request)

    assert key == "ip:203.0.113.5"
