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
