"""Modelo Estado: columnas del tablero Kanban + estados terminales."""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class CategoriaEstado(str, enum.Enum):
    """Categoría funcional del estado (usada para el coloreado del Kanban)."""
    PENDIENTE = "PENDIENTE"          # backlog, no iniciado
    EN_PROGRESO = "EN_PROGRESO"      # trabajo activo
    BLOQUEADO = "BLOQUEADO"          # esperando a otro agente/equipo
    RESUELTO = "RESUELTO"            # trabajo terminado, pendiente de verificación
    CERRADO = "CERRADO"              # estado terminal (no se puede mover)
    CANCELADO = "CANCELADO"          # estado terminal (desestimado)


class Estado(Base):
    """Estado del ciclo de vida de un ticket. Cada estado puede ser una columna Kanban."""
    __tablename__ = "estados"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Posición en el tablero (orden de izquierda a derecha en el Kanban).
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    categoria: Mapped[CategoriaEstado] = mapped_column(
        SAEnum(CategoriaEstado, name="categoria_estado", native_enum=False, length=20),
        nullable=False,
        default=CategoriaEstado.PENDIENTE,
    )

    es_inicial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    es_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Color en formato HEX (#RRGGBB) para la cabecera de la columna.
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#64748b")

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relaciones
    tickets = relationship("Ticket", back_populates="estado")
    transiciones_origen = relationship(
        "Transicion", back_populates="estado_origen", foreign_keys="Transicion.origen_id"
    )
    transiciones_destino = relationship(
        "Transicion", back_populates="estado_destino", foreign_keys="Transicion.destino_id"
    )

    def __repr__(self) -> str:
        return f"<Estado id={self.id} nombre={self.nombre!r} orden={self.orden}>"
