"""
Motor de automatizaciones tipo "Butler" de Trello.

Permite definir reglas: "CUANDO <evento> SI <condición> ENTONCES <acción>".
Las reglas se evalúan automáticamente al ocurrir eventos del ciclo de vida del
ticket (creación, cambio de estado, asignación, comentario, etc.).
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Boolean, JSON, Index
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class ReglaAutomatizacion(Base, TimestampMixin):
    """
    Regla declarativa estilo IFTTT / Trello Butler.

    disparador (trigger):
        - "ticket_creado"
        - "ticket_estado_cambiado"
        - "ticket_asignado"
        - "ticket_comentado"
        - "ticket_etiquetado"
        - "sla_por_vencer"
        - "sla_vencido"
    condiciones: lista de dicts {campo, operador, valor}
        operadores: ==, !=, in, not_in, contains, gt, lt
    acciones: lista de dicts {tipo, parametros}
        tipos: "asignar_a", "cambiar_estado", "agregar_etiqueta",
               "quitar_etiqueta", "crear_comentario", "enviar_notificacion",
               "agregar_checklist", "marcar_prioridad"
    """
    __tablename__ = "reglas_automatizacion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(120), nullable=False)
    descripcion = Column(Text, nullable=True)
    # Trigger principal
    disparador = Column(String(60), nullable=False, index=True)
    # Lista de condiciones y acciones serializadas como JSON
    condiciones = Column(JSON, nullable=False, default=list)
    acciones = Column(JSON, nullable=False, default=list)
    # Orden de evaluación
    prioridad = Column(Integer, default=100, nullable=False, index=True)
    # Si la regla está activa
    activo = Column(Boolean, default=True, nullable=False, index=True)
    # Quién la creó (auditoría)
    creador_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )

    ejecuciones = relationship(
        "EjecucionAutomatizacion",
        back_populates="regla",
        cascade="all, delete-orphan",
        order_by="EjecucionAutomatizacion.created_at.desc()",
    )
    creador = relationship("Usuario")

    __table_args__ = (
        Index("ix_regla_disparador_activo", "disparador", "activo"),
    )

    def __repr__(self) -> str:
        return f"<ReglaAutomatizacion {self.nombre} ({self.disparador})>"


class EjecucionAutomatizacion(Base, TimestampMixin):
    """
    Bitácora de cada ejecución de una regla.
    Permite depurar y medir la efectividad del motor Butler.
    """
    __tablename__ = "ejecuciones_automatizacion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    regla_id = Column(
        Integer, ForeignKey("reglas_automatizacion.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    contexto = Column(JSON, nullable=True)
    exito = Column(Integer, default=1, nullable=False)  # 1=True, 0=False
    detalle = Column(Text, nullable=True)

    regla = relationship("ReglaAutomatizacion", back_populates="ejecuciones")

    def __repr__(self) -> str:
        return f"<EjecucionAutomatizacion regla={self.regla_id} exito={self.exito}>"
