"""
Modelo Auditoria: registro obligatorio e inmutable de cada cambio relevante.
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Auditoria(Base, TimestampMixin):
    """
    Bitácora de auditoría del sistema. Se inserta un registro por:
    - Cambio de estado (drag & drop en Kanban)
    - Asignación
    - Edición de campos
    - Cierre
    """
    __tablename__ = "auditorias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ticket_id es NULLABLE: la tabla registra eventos tanto de tickets
    # (cambio de estado, asignación, cierre) como de usuarios/seguridad
    # (envío de credenciales, login, edición de perfil). Para los eventos
    # no asociados a un ticket, ticket_id queda en NULL.
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    accion = Column(String(80), nullable=False, index=True)
    valor_anterior = Column(JSON, nullable=True)
    valor_nuevo = Column(JSON, nullable=True)
    comentario = Column(Text, nullable=True)
    ip_origen = Column(String(64), nullable=True)

    # Relaciones
    ticket = relationship("Ticket", back_populates="auditorias")
    usuario = relationship("Usuario", back_populates="auditorias")

    def __repr__(self) -> str:
        return f"<Auditoria ticket={self.ticket_id} accion={self.accion}>"
