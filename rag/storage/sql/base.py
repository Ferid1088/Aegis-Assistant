from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from rag.config import settings


class Base(DeclarativeBase):
    pass


_engine = None


def get_engine():
    """Lazily create and cache the SQLAlchemy engine from the *current*
    settings.database_url.

    Not built at import time: install.py mutates settings.database_url
    mid-process (after generating a real POSTGRES_PASSWORD and writing it
    to .env), and reset_engine() must be called afterward for that change
    to actually take effect -- an engine built once at import time, before
    the real password exists, would silently keep using the stale
    dev-default for the rest of that process (Phase 8.10b).
    """
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    """Dispose of and clear the cached engine so the next get_engine() call
    rebuilds it from a since-changed settings.database_url."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def SessionLocal() -> Session:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
