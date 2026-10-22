"""Modelo Usuario con roles ITSM."""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RolUsuario(str, enum.Enum):
    """Roles del sistema, en orden de menor a mayor privilegio."""
    SOLICITANTE = "SOLICITANTE"
    AGENTE = "AGENTE"
    AGENTE_SENIOR = "AGENTE_SENIOR"
    ADMINISTRADOR = "ADMINISTRADOR"
    OBSERVADOR = "OBSERVADOR"


class Usuario(Base):
    """Cuenta de usuario del sistema. Autenticación por username + password hash."""
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    rol: Mapped[RolUsuario] = mapped_column(
        SAEnum(RolUsuario, name="rol_usuario", native_enum=False, length=20),
        nullable=False,
        default=RolUsuario.SOLICITANTE,
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relaciones
    tickets_creados = relationship("Ticket", back_populates="creador", foreign_keys="Ticket.creador_id")
    tickets_asignados = relationship("Ticket", back_populates="asignado", foreign_keys="Ticket.asignado_id")

    def __repr__(self) -> str:
        return f"<Usuario id={self.id} username={self.username!r} rol={self.rol.value}>"

    @property
    def es_admin(self) -> bool:
        return self.rol == RolUsuario.ADMINISTRADOR

    @property
    def puede_cerrar_ticket(self) -> bool:
        return self.rol in (RolUsuario.AGENTE_SENIOR, RolUsuario.ADMINISTRADOR)
