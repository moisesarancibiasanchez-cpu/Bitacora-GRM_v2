"""Modelo SLAPolitica: reglas de tiempo para calcular vencimientos.

Las políticas se aplican según la prioridad del ticket. Celery recalcula
los SLAs cuando un ticket cambia de estado o prioridad.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from .ticket import PrioridadTicket


class SLAPolitica(Base):
    """Política de SLA. minutos_resolucion = tiempo máximo para resolver el ticket."""
    __tablename__ = "sla_politicas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    prioridad: Mapped[PrioridadTicket] = mapped_column(
        SAEnum(PrioridadTicket, name="prioridad_ticket", native_enum=False, length=10),
        nullable=False,
        index=True,
    )
    minutos_resolucion: Mapped[int] = mapped_column(Integer, nullable=False)

    # Si True, la política aplica por defecto (solo una puede estar activa por prioridad).
    es_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<SLAPolitica id={self.id} prioridad={self.prioridad.value} "
            f"min={self.minutos_resolucion}>"
        )
