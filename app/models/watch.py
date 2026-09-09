"""
Modelos para Watch (suscripciones) y Reacciones.
- Watch: un usuario observa una tarjeta, lista, tablero o espacio y
  recibe notificaciones por cada cambio.
- Reaccion: respuesta rápida con emoji en comentarios o tarjetas.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Boolean, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Watch(Base, TimestampMixin):
    """
    Suscripción de un usuario a un elemento del sistema.
    Permite "observar" y recibir notificaciones sin estar asignado.
    tipos: 'ticket' | 'tablero' | 'espacio' | 'lista' (estado)
    """
    __tablename__ = "watches"
    __table_args__ = (
        Index("ix_watch_usuario_tipo_objeto", "usuario_id", "tipo_objeto", "objeto_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # tipo_objeto: ticket | tablero | espacio | lista
    tipo_objeto = Column(String(20), nullable=False, index=True)
    objeto_id = Column(Integer, nullable=False, index=True)
    # Si está activo (puede desactivarse sin eliminar)
    activo = Column(Boolean, default=True, nullable=False)
    # Canal preferido de notificación: 'web' | 'email' | 'push' | 'all'
    canal = Column(String(20), default="all", nullable=False)

    # Relaciones polimórficas condicionales (no FK para soportar múltiples tipos)
    usuario = relationship("Usuario", backref="watches")

    def __repr__(self) -> str:
        return f"<Watch usuario={self.usuario_id} {self.tipo_objeto}:{self.objeto_id}>"


class Reaccion(Base, TimestampMixin):
    """
    Reacción emoji sobre un comentario o ticket.
    Cada usuario puede reaccionar una vez por emoji a cada objeto.
    """
    __tablename__ = "reacciones"
    __table_args__ = (
        UniqueConstraint("usuario_id", "tipo_objeto", "objeto_id", "emoji", name="uq_reaccion_unica"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # tipo_objeto: 'comentario' | 'ticket'
    tipo_objeto = Column(String(20), nullable=False, index=True)
    objeto_id = Column(Integer, nullable=False, index=True)
    # Emoji Unicode (👍 ❤️ 🎉 😄 🤔 👀 🚀 etc.)
    emoji = Column(String(16), nullable=False, index=True)

    usuario = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<Reaccion {self.emoji} {self.tipo_objeto}:{self.objeto_id}>"


class Notificacion(Base, TimestampMixin):
    """
    Notificación generada para un usuario (cola de bandeja).
    Se crea a partir de menciones, watches, asignaciones, etc.
    """
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # Tipo: 'mencion' | 'asignacion' | 'watch' | 'estado' | 'comentario' | 'sla'
    tipo = Column(String(30), nullable=False, index=True)
    # Referencia al objeto (ticket, comentario, etc.)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    # Título y mensaje legibles
    titulo = Column(String(200), nullable=False)
    mensaje = Column(Text, nullable=False)
    # Si ya fue leída
    leida = Column(Boolean, default=False, nullable=False, index=True)
    # Si fue leída, cuándo
    leida_en = Column(String(50), nullable=True)
    # URL para ir al recurso
    url = Column(String(500), nullable=True)
    # Quién originó la notificación (opcional)
    origen_usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )

    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    origen = relationship("Usuario", foreign_keys=[origen_usuario_id])
    ticket = relationship("Ticket")

    def __repr__(self) -> str:
        return f"<Notificacion {self.tipo} usuario={self.usuario_id} leida={self.leida}>"
