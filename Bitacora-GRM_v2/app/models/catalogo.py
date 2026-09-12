"""
Modelos base para los mantenedores de catálogos del sistema.
Permite definir esquemas dinámicos (JSON) que el módulo de incidencias puede usar.
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class CatalogoTipo(Base, TimestampMixin):
    """
    Define un tipo de catálogo con un esquema de campos (JSON Schema simplificado).
    Ejemplos: 'Equipos', 'Servicios', 'Proveedores', 'Sistemas afectados'.
    """
    __tablename__ = "catalogo_tipos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(120), unique=True, nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    # Esquema simplificado: lista de campos {"key", "label", "tipo", "requerido"}
    esquema = Column(JSON, nullable=False, default=list)
    activo = Column(Boolean, default=True, nullable=False)

    # Relaciones
    items = relationship(
        "CatalogoItem",
        back_populates="catalogo_tipo",
        cascade="all, delete-orphan",
    )
    tickets = relationship("Ticket", back_populates="catalogo_tipo")

    def __repr__(self) -> str:
        return f"<CatalogoTipo {self.nombre}>"


class CatalogoItem(Base, TimestampMixin):
    """
    Un ítem/registro dentro de un catálogo.
    Los valores se almacenan en `datos` siguiendo el esquema del tipo padre.
    """
    __tablename__ = "catalogo_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalogo_tipo_id = Column(
        Integer, ForeignKey("catalogo_tipos.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    nombre = Column(String(200), nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    datos = Column(JSON, nullable=False, default=dict)
    activo = Column(Boolean, default=True, nullable=False)

    catalogo_tipo = relationship("CatalogoTipo", back_populates="items")

    def __repr__(self) -> str:
        return f"<CatalogoItem {self.nombre} tipo_id={self.catalogo_tipo_id}>"
