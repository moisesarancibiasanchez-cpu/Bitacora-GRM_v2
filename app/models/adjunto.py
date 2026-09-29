"""
Modelo Adjunto: archivos subidos a un ticket (evidencia, logs, screenshots).
"""
import os
from sqlalchemy import Column, Integer, String, Text, ForeignKey, BigInteger, LargeBinary
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Adjunto(Base, TimestampMixin):
    """
    Archivo adjunto a un ticket.

    Almacenamiento dual para sobrevivir al filesystem efímero de Railway:
    * ``ruta``     → ruta en disco (rápido, fuente principal).
    * ``contenido``→ copia del archivo como ``BYTEA`` en la propia BD (respaldo
                     persistente que sobrevive a redeploys y reinicios del
                     contenedor). Si la fila se subió ANTES de esta columna
                     puede estar ``NULL`` → solo disco.
    """
    __tablename__ = "adjuntos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False
    )
    nombre_original = Column(String(255), nullable=False)
    nombre_storage = Column(String(255), nullable=False, unique=True)
    ruta = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    tamano_bytes = Column(BigInteger, default=0, nullable=False)
    descripcion = Column(Text, nullable=True)
    # Respaldo binario en BD (NULL en registros antiguos; se rellena en cada
    # subida nueva). En SQLite se persiste como ``BLOB`` y en PostgreSQL como
    # ``BYTEA`` (columna ``oid`` evitada para mantener updates por registro).
    contenido = Column(LargeBinary, nullable=True)

    ticket = relationship("Ticket", back_populates="adjuntos", foreign_keys=[ticket_id])
    usuario = relationship("Usuario")

    @property
    def tamano_legible(self) -> str:
        """Devuelve el tamaño en formato legible (KB, MB, etc)."""
        size = float(self.tamano_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    @property
    def es_imagen(self) -> bool:
        return (self.mime_type or "").startswith("image/")

    @property
    def disponible(self) -> bool:
        """True si el archivo físico está en disco O tiene respaldo en BD."""
        if self.contenido:
            return True
        try:
            return bool(self.ruta) and os.path.exists(self.ruta)
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"<Adjunto {self.nombre_original} ticket={self.ticket_id}>"
