"""Modelo AuditoriaEvento: registro inmutable de TODOS los cambios relevantes del ticket.

OBLIGATORIO: cada vez que un ticket cambia de estado, se inserta un registro aquí.
"""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Enum as SAEnum, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TipoEvento(str, enum.Enum):
    """Tipos de eventos auditables. Cualquier cambio relevante debe tener uno."""
    CREADO = "CREADO"
    ESTADO_CAMBIADO = "ESTADO_CAMBIADO"
    REASIGNADO = "REASIGNADO"
    PRIORIDAD_CAMBIADA = "PRIORIDAD_CAMBIADO"
    COMENTARIO_AGREGADO = "COMENTARIO_AGREGADO"
    ADJUNTO_AGREGADO = "ADJUNTO_AGREGADO"
    SLA_CALCULADO = "SLA_CALCULADO"
    NOTIFICACION_ENVIADA = "NOTIFICACION_ENVIADA"


class AuditoriaEvento(Base):
    """Registro append-only de eventos del ticket. NO se actualiza ni elimina."""
    __tablename__ = "auditoria_eventos"
    __table_args__ = (
        Index("ix_auditoria_ticket_fecha", "ticket_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tipo: Mapped[TipoEvento] = mapped_column(
        SAEnum(TipoEvento, name="tipo_evento", native_enum=False, length=30),
        nullable=False,
        index=True,
    )

    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    actor_username: Mapped[str] = mapped_column(String(64), nullable=False, default="system")

    # Valores antes / después (en JSON serializado) para reconstruir el cambio.
    valor_anterior: Mapped[str] = mapped_column(Text, nullable=False, default="")
    valor_nuevo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    comentario: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Relación
    ticket = relationship("Ticket", back_populates="eventos_auditoria")

    def __repr__(self) -> str:
        return (
            f"<AuditoriaEvento id={self.id} ticket_id={self.ticket_id} "
            f"tipo={self.tipo.value} actor={self.actor_username!r}>"
        )
