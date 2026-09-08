"""
Modelos para Etiquetas (Labels) de tickets.
Sistema many-to-many: una etiqueta puede estar en muchos tickets
y un ticket puede tener muchas etiquetas.
"""
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Boolean, Table, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


# Tabla de asociación many-to-many entre tickets y etiquetas
ticket_etiquetas = Table(
    "ticket_etiquetas",
    Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("etiqueta_id", Integer, ForeignKey("etiquetas.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", String(50), nullable=True),
)


class Etiqueta(Base, TimestampMixin):
    """
    Etiqueta de clasificación visual (similar a Labels de Trello).
    Se puede usar para categorizar, marcar urgencia, tipo de problema, etc.
    """
    __tablename__ = "etiquetas"
    __table_args__ = (
        UniqueConstraint("nombre", "categoria", name="uq_etiqueta_nombre_categoria"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(60), nullable=False, index=True)
    # Color en formato hexadecimal (#FF0000)
    color = Column(String(20), default="#6b7280", nullable=False)
    # Categoría opcional: 'urgencia', 'tipo', 'area', 'impacto'
    categoria = Column(String(40), default="general", nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, nullable=False)

    # Relación many-to-many
    tickets = relationship(
        "Ticket",
        secondary=ticket_etiquetas,
        back_populates="etiquetas",
    )

    def __repr__(self) -> str:
        return f"<Etiqueta {self.nombre} ({self.color})>"
