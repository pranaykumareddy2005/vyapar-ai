"""Database engine, session factory, and the declarative ORM base.

Uses SQLAlchemy 2.0 typed style. Sessions are provided to the API layer through
:func:`get_session` (a FastAPI dependency). Services own their transaction
boundaries explicitly (``with session.begin(): ...``) per the LLD.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models across domain modules."""


_settings = get_settings()

engine = create_engine(
    _settings.db_url,
    echo=_settings.debug,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session and always closing it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
