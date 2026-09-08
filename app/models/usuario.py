"""
Modelo Usuario: gestiona los agentes y solicitantes del sistema.
"""
from sqlalchemy import Column, Integer, String, Boolean, Enum
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base, TimestampMixin


class RolUsuario(str, enum.Enum):
    """Roles disponibles con permisos predefinidos."""
    ADMINISTRADOR = "administrador"
    AGENTE_SENIOR = "agente_senior"
    AGENTE = "agente"
    SOLICITANTE = "solicitante"
    OBSERVADOR = "observador"


class Usuario(Base, TimestampMixin):
    """Usuario del sistema (agente, administrador, solicitante)."""
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    nombre_completo = Column(String(200), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    rol = Column(Enum(RolUsuario), nullable=False, default=RolUsuario.SOLICITANTE, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    departamento = Column(String(120), nullable=True)

    # Relaciones
    tickets_creados = relationship(
        "Ticket",
        back_populates="creador",
        foreign_keys="Ticket.creador_id",
        cascade="all, delete-orphan",
    )
    tickets_asignados = relationship(
        "Ticket",
        back_populates="asignado",
        foreign_keys="Ticket.asignado_id",
    )
    auditorias = relationship("Auditoria", back_populates="usuario")

    def tiene_permiso_para(self, accion: str) -> bool:
        """Verifica si el rol del usuario permite una acción dada."""
        permisos = {
            RolUsuario.ADMINISTRADOR: {"*"},
            RolUsuario.AGENTE_SENIOR: {
                "cambiar_estado", "reasignar", "cerrar_ticket",
                "editar_ticket", "ver_auditoria", "agregar_comentario",
            },
            RolUsuario.AGENTE: {
                "cambiar_estado", "agregar_comentario", "editar_ticket",
            },
            RolUsuario.SOLICITANTE: {"crear_ticket", "agregar_comentario"},
            RolUsuario.OBSERVADOR: {"ver_auditoria"},
        }
        return (
            "*" in permisos.get(self.rol, set())
            or accion in permisos.get(self.rol, set())
        )

    def __repr__(self) -> str:
        return f"<Usuario {self.username} ({self.rol.value})>"
