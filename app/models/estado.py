"""
Modelos para el flujo de estados ITSM y sus transiciones válidas.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, UniqueConstraint, Text
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Estado(Base, TimestampMixin):
    """
    Estado de un ticket dentro del flujo de trabajo (columna del Kanban).
    Ejemplos: 'Nuevo', 'En curso', 'En espera', 'Resuelto', 'Cerrado'.
    """
    __tablename__ = "estados"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(80), unique=True, nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    # Color para identificar visualmente la columna en el Kanban
    color = Column(String(20), default="#94a3b8", nullable=False)
    # Orden de aparición en el tablero
    orden = Column(Integer, default=0, nullable=False, index=True)
    es_inicial = Column(Boolean, default=False, nullable=False)
    es_final = Column(Boolean, default=False, nullable=False)
    # Categoría para agrupación en reportes
    categoria = Column(String(40), default="abierto", nullable=False)
    # SLA por defecto en horas cuando un ticket entra en este estado
    sla_horas = Column(Integer, nullable=True)

    # Relaciones
    transiciones_salida = relationship(
        "TransicionEstado",
        back_populates="estado_origen",
        foreign_keys="TransicionEstado.estado_origen_id",
        cascade="all, delete-orphan",
    )
    tickets = relationship("Ticket", back_populates="estado")

    def __repr__(self) -> str:
        return f"<Estado {self.nombre} (orden={self.orden})>"


class TransicionEstado(Base):
    """
    Define las transiciones legales entre estados del flujo ITSM.
    Es la base de la validación: solo se permite mover de A a B si existe registro aquí.
    """
    __tablename__ = "transiciones_estado"
    __table_args__ = (
        UniqueConstraint(
            "estado_origen_id", "estado_destino_id",
            name="uq_transicion_origen_destino",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    estado_origen_id = Column(
        Integer, ForeignKey("estados.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estado_destino_id = Column(
        Integer, ForeignKey("estados.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Rol mínimo necesario para ejecutar la transición
    rol_requerido = Column(String(40), default="agente", nullable=False)
    # Comentario obligatorio (ej. "Cerrado: requiere motivo")
    requiere_comentario = Column(Boolean, default=False, nullable=False)
    descripcion = Column(String(200), nullable=True)

    # Relaciones
    estado_origen = relationship(
        "Estado", back_populates="transiciones_salida", foreign_keys=[estado_origen_id]
    )
    estado_destino = relationship("Estado", foreign_keys=[estado_destino_id])

    def __repr__(self) -> str:
        return (
            f"<Transicion {self.estado_origen_id} -> {self.estado_destino_id} "
            f"(rol={self.rol_requerido})>"
        )
