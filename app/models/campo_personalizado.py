"""
Modelos para Campos Personalizados (Custom Fields) estilo Trello Power-Up.
Permite añadir estructuras de datos tipadas a las tarjetas:
- Texto
- Número
- Lista desplegable (dropdown)
- Casilla de verificación (checkbox)
- Fecha
- URL
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, ForeignKey, JSON, Index, Float, DateTime
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class CampoPersonalizado(Base, TimestampMixin):
    """
    Definición de un campo personalizado en un tablero.
    tipo: 'texto' | 'numero' | 'dropdown' | 'checkbox' | 'fecha' | 'url'
    configuracion: opciones específicas del tipo (ej. opciones del dropdown)
    """
    __tablename__ = "campos_personalizados"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tablero_id = Column(
        Integer, ForeignKey("tableros.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    nombre = Column(String(80), nullable=False)
    # Tipo de dato
    tipo = Column(String(20), nullable=False, index=True)
    # Configuración adicional según tipo:
    #   - dropdown: {"opciones": ["Alta", "Media", "Baja"]}
    #   - numero:   {"min": 0, "max": 100, "decimales": 2}
    #   - texto:    {"max_length": 200, "placeholder": "..."}
    configuracion = Column(JSON, nullable=True)
    # Si es obligatorio
    requerido = Column(Boolean, default=False, nullable=False)
    # Posición de aparición
    posicion = Column(Integer, default=0, nullable=False)
    # Si está activo
    activo = Column(Boolean, default=True, nullable=False)
    # Color del campo en la UI
    color = Column(String(20), default="#6366f1", nullable=False)

    # Relaciones
    tablero = relationship("Tablero", back_populates="campos_personalizados")
    valores = relationship(
        "ValorCampo",
        back_populates="campo",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_campo_tablero_posicion", "tablero_id", "posicion"),
    )

    def __repr__(self) -> str:
        return f"<CampoPersonalizado {self.nombre} ({self.tipo})>"


class ValorCampo(Base, TimestampMixin):
    """
    Valor de un campo personalizado para un ticket específico.
    valor_texto: para tipos texto, url, dropdown
    valor_numero: para tipo numero
    valor_booleano: para tipo checkbox
    valor_fecha: para tipo fecha
    """
    __tablename__ = "valores_campo"
    __table_args__ = (
        Index("uq_valor_campo_ticket", "campo_id", "ticket_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    campo_id = Column(
        Integer, ForeignKey("campos_personalizados.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # Almacenamiento polimórfico según el tipo
    valor_texto = Column(Text, nullable=True)
    valor_numero = Column(Float, nullable=True)
    valor_booleano = Column(Boolean, nullable=True)
    valor_fecha = Column(DateTime, nullable=True)

    campo = relationship("CampoPersonalizado", back_populates="valores")
    ticket = relationship("Ticket", backref="valores_campos")

    @property
    def valor(self):
        """Devuelve el valor en su tipo nativo."""
        if self.valor_texto is not None:
            return self.valor_texto
        if self.valor_numero is not None:
            return self.valor_numero
        if self.valor_booleano is not None:
            return self.valor_booleano
        if self.valor_fecha is not None:
            return self.valor_fecha
        return None

    def __repr__(self) -> str:
        return f"<ValorCampo campo={self.campo_id} ticket={self.ticket_id}={self.valor}>"
