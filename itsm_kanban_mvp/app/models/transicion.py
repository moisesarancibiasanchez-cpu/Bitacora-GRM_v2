"""Modelo Transicion: reglas ITSM que controlan los cambios de estado legales."""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from .usuario import RolUsuario


class RolRequerido(str, enum.Enum):
    """Rol mínimo del usuario para ejecutar la transición."""
    CUALQUIERA = "CUALQUIERA"            # cualquier usuario autenticado
    SOLICITANTE = "SOLICITANTE"
    AGENTE = "AGENTE"
    AGENTE_SENIOR = "AGENTE_SENIOR"
    ADMINISTRADOR = "ADMINISTRADOR"


class Transicion(Base):
    """Regla de transición de estado: define qué origen → destino es legal y qué rol se requiere.

    La unicidad (origen_id, destino_id) impide reglas duplicadas.
    """
    __tablename__ = "transiciones"
    __table_args__ = (UniqueConstraint("origen_id", "destino_id", name="uq_transicion_origen_destino"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    origen_id: Mapped[int] = mapped_column(ForeignKey("estados.id", ondelete="CASCADE"), nullable=False, index=True)
    destino_id: Mapped[int] = mapped_column(ForeignKey("estados.id", ondelete="CASCADE"), nullable=False, index=True)

    nombre: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    rol_requerido: Mapped[RolRequerido] = mapped_column(
        SAEnum(RolRequerido, name="rol_requerido", native_enum=False, length=20),
        nullable=False,
        default=RolRequerido.AGENTE,
    )

    # Si True, se exige un comentario al ejecutar la transición (justificación).
    requiere_comentario: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Si True, dispara una tarea asíncrona en Celery (recalcular SLA + notificar).
    dispara_recalculo_sla: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relaciones
    estado_origen = relationship("Estado", back_populates="transiciones_origen", foreign_keys=[origen_id])
    estado_destino = relationship("Estado", back_populates="transiciones_destino", foreign_keys=[destino_id])

    def __repr__(self) -> str:
        return (
            f"<Transicion id={self.id} {self.origen_id}→{self.destino_id} "
            f"rol={self.rol_requerido.value}>"
        )

    def usuario_tiene_permiso(self, rol: RolUsuario) -> bool:
        """Verifica si el rol del usuario satisface el mínimo requerido por la transición."""
        orden = {
            RolRequerido.CUALQUIERA: 0,
            RolRequerido.SOLICITANTE: 1,
            RolRequerido.AGENTE: 2,
            RolRequerido.AGENTE_SENIOR: 3,
            RolRequerido.ADMINISTRADOR: 4,
        }
        # Mapeo de roles de Usuario a su "nivel" para comparar contra orden.
        nivel_rol = {
            RolUsuario.SOLICITANTE: 1,
            RolUsuario.AGENTE: 2,
            RolUsuario.AGENTE_SENIOR: 3,
            RolUsuario.ADMINISTRADOR: 4,
            RolUsuario.OBSERVADOR: 0,
        }
        return nivel_rol.get(rol, 0) >= orden.get(self.rol_requerido, 99)
