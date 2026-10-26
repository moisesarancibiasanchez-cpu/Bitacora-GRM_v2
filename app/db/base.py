"""
Base declarativa de SQLAlchemy. Todos los modelos heredan de aquí.
"""
from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase

from app.core.timezone import now_utc


class Base(DeclarativeBase):
    """Clase base con campos comunes de auditoría (created_at, updated_at)."""
    pass


class TimestampMixin:
    """Mixin con timestamps automáticos.

    Usa ``now_utc()`` (naive UTC) y no ``datetime.utcnow()``: el valor es
    idéntico, pero ``utcnow`` está deprecado desde Python 3.12 (la versión
    de Python del proyecto) y ``now_utc()`` es la función autorizada por
    la convención de zona horaria del repositorio.
    """
    created_at = Column(
        DateTime, default=now_utc, nullable=False, index=True
    )
    updated_at = Column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
        nullable=False,
    )
