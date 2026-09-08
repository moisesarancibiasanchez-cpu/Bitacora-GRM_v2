"""
Base declarativa de SQLAlchemy. Todos los modelos heredan de aquí.
"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Clase base con campos comunes de auditoría (created_at, updated_at)."""
    pass


class TimestampMixin:
    """Mixin con timestamps automáticos."""
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
