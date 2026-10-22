"""
Sesión de SQLAlchemy: motor + SessionLocal.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings


def _build_engine_kwargs():
    url = settings.get_database_url()
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "echo": settings.DEBUG}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20, "echo": settings.DEBUG}


engine = create_engine(settings.get_database_url(), **_build_engine_kwargs())

SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)


def get_db() -> Session:
    """Dependencia FastAPI para inyectar una sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
