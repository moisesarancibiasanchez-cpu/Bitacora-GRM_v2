"""Modelo Ticket: la entidad principal del sistema (incidencia / caso)."""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Enum as SAEnum, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from .usuario import Usuario


class PrioridadTicket(str, enum.Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class Ticket(Base):
    """Ticket / Incidencia. Cada ticket pertenece a un estado del Kanban."""
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_estado_orden", "estado_id", "posicion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    codigo: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    estado_id: Mapped[int] = mapped_column(
        ForeignKey("estados.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    prioridad: Mapped[PrioridadTicket] = mapped_column(
        SAEnum(PrioridadTicket, name="prioridad_ticket", native_enum=False, length=10),
        nullable=False,
        default=PrioridadTicket.MEDIA,
    )

    creador_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    asignado_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Posición dentro de la columna Kanban (orden manual al arrastrar).
    posicion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # SLA: plazos y vencimientos.
    fecha_vencimiento_sla: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_cumplido: Mapped[bool | None] = mapped_column(nullable=True)  # None=sin calcular, True/False

    # Metadata adicional (JSON serializado). Útil para campos personalizados futuros.
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relaciones
    estado = relationship("Estado", back_populates="tickets")
    creador = relationship("Usuario", back_populates="tickets_creados", foreign_keys=[creador_id])
    asignado = relationship("Usuario", back_populates="tickets_asignados", foreign_keys=[asignado_id])
    eventos_auditoria = relationship(
        "AuditoriaEvento", back_populates="ticket", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Ticket id={self.id} codigo={self.codigo!r} estado_id={self.estado_id}>"
