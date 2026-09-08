"""
Modelo Comentario: discusión en un ticket con soporte para @menciones.
"""
import re
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Comentario(Base, TimestampMixin):
    """
    Comentario en un ticket. Soporta @menciones que notifican a usuarios.
    """
    __tablename__ = "comentarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    texto = Column(Text, nullable=False)
    # Si es True, el comentario es solo para el equipo (interno), no se muestra al solicitante
    es_interno = Column(Boolean, default=False, nullable=False)
    # Si fue edición, guarda el original
    editado = Column(Boolean, default=False, nullable=False)
    texto_original = Column(Text, nullable=True)

    ticket = relationship("Ticket", back_populates="comentarios")
    usuario = relationship("Usuario")
    menciones = relationship(
        "MencionUsuario",
        back_populates="comentario",
        cascade="all, delete-orphan",
    )

    def extraer_menciones(self) -> list:
        """Extrae los usernames mencionados con @ del texto del comentario."""
        patron = r'@(\w+)'
        return list(set(re.findall(patron, self.texto)))

    def __repr__(self) -> str:
        return f"<Comentario ticket={self.ticket_id} usuario={self.usuario_id}>"


class MencionUsuario(Base):
    """
    Relación usuario mencionado en un comentario.
    Se usa para enviar notificaciones.
    """
    __tablename__ = "menciones_usuario"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comentario_id = Column(
        Integer, ForeignKey("comentarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # Si ya se le notificó
    notificado = Column(Integer, default=0, nullable=False)  # 0=False, 1=True

    comentario = relationship("Comentario", back_populates="menciones")
    usuario = relationship("Usuario")
