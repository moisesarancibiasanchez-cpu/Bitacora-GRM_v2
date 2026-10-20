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
    # ---------------------------------------------------------------------------
    # FEATURE — Archivos adjuntos del comentario.
    #
    # ``cascade="all, delete-orphan"`` + el ``ON DELETE CASCADE`` de la FK
    # garantizan que al borrar un comentario se borren también sus archivos
    # (en disco se limpia vía el endpoint DELETE /adjuntos/{id}; el backup en
    # BD desaparece solo con la fila).
    #
    # Nota: ``passive_deletes=True`` NO se usa a propósito — sin él, SQLAlchemy
    # intenta poner ``adjuntos.comentario_id = NULL`` en vez de borrar filas,
    # lo que fallaría con la columna NOT NULL histórica ``ticket_id`` en el
    # borde de la cascada. El borrado en cascada lo resuelve la BD.
    # ---------------------------------------------------------------------------
    adjuntos = relationship(
        "Adjunto",
        back_populates="comentario",
        cascade="all, delete-orphan",
        order_by="Adjunto.created_at.asc()",
    )

    def extraer_menciones(self) -> list:
        """Extrae los usernames mencionados con @ del texto del comentario."""
        patron = r'@(\w+)'
        return list(set(re.findall(patron, self.texto or "")))

    # ---------------------------------------------------------------------------
    # FEATURE — Referencias entre comentarios (``#ID``).
    #
    # Un comentario puede "linkear" a otro escribiendo su ID con el prefijo
    # ``#`` (p. ej. ``"#482 estaba equivocado, lo corrijo abajo"``). El parser
    # usa un lookbehind negativo para NO capturar:
    #   * correos      → ``tickets#12@x.com``
    #   * issue de GitHub → ``ORG/repo#12``
    #   * hexadecimales precedidos por 0x → ``0x#...`` (caso borde)
    # Devuelve IDs únicos y ordenados, excluyendo la autorreferencia.
    # ---------------------------------------------------------------------------
    PATRON_REFERENCIA = r'(?<![\w@/])#(\d+)'

    def extraer_referencias(self) -> list:
        """Devuelve la lista de IDs de comentarios referenciados con ``#ID``."""
        if not self.texto:
            return []
        encontrados = {
            int(m) for m in re.findall(self.PATRON_REFERENCIA, self.texto)
        }
        encontrados.discard(self.id)
        return sorted(encontrados)

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
