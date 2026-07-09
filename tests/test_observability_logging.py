import io
import json
import logging

import structlog

from rag.observability.logging_config import configure_logging


def test_configure_logging_produces_json_with_bound_request_id():
    configure_logging()
    stream = io.StringIO()
    logging.getLogger().handlers[0].stream = stream

    structlog.contextvars.bind_contextvars(request_id="test-request-123")
    try:
        structlog.get_logger("test").info("hello")
    finally:
        structlog.contextvars.clear_contextvars()

    output = json.loads(stream.getvalue().strip())
    assert output["event"] == "hello"
    assert output["request_id"] == "test-request-123"
    assert output["level"] == "info"


def test_clear_contextvars_removes_request_id_from_later_log_lines():
    configure_logging()
    stream = io.StringIO()
    logging.getLogger().handlers[0].stream = stream

    structlog.contextvars.bind_contextvars(request_id="test-request-456")
    structlog.contextvars.clear_contextvars()
    structlog.get_logger("test").info("hello again")

    output = json.loads(stream.getvalue().strip())
    assert "request_id" not in output
