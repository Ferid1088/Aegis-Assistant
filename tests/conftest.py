import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def pytest_configure(config):
    """Configure test environment before any imports that depend on settings."""
    # Patch settings.redis_url before importing any modules that use it
    patch("rag.config.settings.redis_url", "redis://localhost:6379").start()


@pytest.fixture()
def db_session():
    """In-memory SQLite session with all rag.storage.sql models' tables created.
    Used for fast, DB-backed unit tests that don't need real Postgres."""
    from rag.storage.sql import models  # noqa: F401  (registers models on Base.metadata)
    from rag.storage.sql.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
