from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rag.storage.sql.base import Base


def test_get_db_yields_working_session(monkeypatch):
    # Use an in-memory sqlite engine instead of the real Postgres URL for this test.
    engine = create_engine("sqlite://")
    TestSessionLocal = sessionmaker(bind=engine)

    import rag.storage.sql.base as base_module
    monkeypatch.setattr(base_module, "SessionLocal", TestSessionLocal)

    gen = base_module.get_db()
    db = next(gen)
    result = db.execute(text("SELECT 1")).scalar()
    assert result == 1
    gen.close()


def test_base_is_declarative_base():
    assert hasattr(Base, "metadata")


def test_get_engine_caches_the_engine_instance():
    import rag.storage.sql.base as base_module

    base_module.reset_engine()  # start from a clean slate regardless of test order
    try:
        first = base_module.get_engine()
        second = base_module.get_engine()
        assert first is second
    finally:
        base_module.reset_engine()


def test_reset_engine_rebuilds_from_a_changed_database_url(monkeypatch):
    import rag.storage.sql.base as base_module
    from rag.config import settings

    base_module.reset_engine()
    try:
        monkeypatch.setattr(settings, "database_url", "sqlite:///first.db")
        first = base_module.get_engine()
        assert str(first.url) == "sqlite:///first.db"

        monkeypatch.setattr(settings, "database_url", "sqlite:///second.db")
        # Without reset_engine(), get_engine() still returns the cached first
        # engine -- this is exactly the bug this task fixes (install.py
        # mutating settings.database_url mid-process had no effect before).
        assert base_module.get_engine() is first

        base_module.reset_engine()
        second = base_module.get_engine()
        assert second is not first
        assert str(second.url) == "sqlite:///second.db"
    finally:
        base_module.reset_engine()


def test_session_local_returns_session_bound_to_current_engine(monkeypatch):
    import rag.storage.sql.base as base_module
    from rag.config import settings

    base_module.reset_engine()
    try:
        monkeypatch.setattr(settings, "database_url", "sqlite://")
        session = base_module.SessionLocal()
        try:
            assert session.get_bind() is base_module.get_engine()
        finally:
            session.close()
    finally:
        base_module.reset_engine()
