"""Modelo CatalogoItem: base para futuros mantenedores de catálogos.

El MVP siembra algunos catálogos (TipoTicket, Categoria) y los expone en
endpoints read-only. La tabla está diseñada para extender con más catálogos.
"""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TipoCatalogo(str, enum.Enum):
    """Tipo de catálogo. Permite extender con más tipos sin migraciones."""
    TIPO_TICKET = "TIPO_TICKET"
    CATEGORIA = "CATEGORIA"
    ETIQUETA = "ETIQUETA"
    MODULO = "MODULO"


class CatalogoItem(Base):
    """Ítem de catálogo. Tabla única para todos los catálogos (tipo discrimina)."""
    __tablename__ = "catalogo_items"
    __table_args__ = (UniqueConstraint("tipo", "codigo", name="uq_catalogo_tipo_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoCatalogo] = mapped_column(
        SAEnum(TipoCatalogo, name="tipo_catalogo", native_enum=False, length=20),
        nullable=False,
        index=True,
    )
    codigo: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(128), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#64748b")

    # Para jerarquías (ej. Categoria > Subcategoria).
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalogo_items.id", ondelete="SET NULL"), nullable=True
    )

    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    parent = relationship("CatalogoItem", remote_side=[id], backref="hijos")

    def __repr__(self) -> str:
        return f"<CatalogoItem id={self.id} tipo={self.tipo.value} codigo={self.codigo!r}>"
