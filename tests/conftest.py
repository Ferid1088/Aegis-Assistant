import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def db_session():
    """In-memory SQLite session with all rag.infra.stores.sql models' tables created.
    Used for fast, DB-backed unit tests that don't need real Postgres."""
    from rag.infra.stores.sql import models  # noqa: F401  (registers models on Base.metadata)
    from rag.infra.stores.sql.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
