"""SQLAlchemy engine, session factory, y dependency para FastAPI."""
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.core.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Clase base para todos los modelos SQLAlchemy 2.0."""
    pass


def get_db() -> Session:
    """Dependency de FastAPI que abre y cierra una sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
