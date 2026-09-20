"""
Modelo TicketDependencia (FEATURE 3: Gantt con dependencias).

Representa una relación de precedencia entre dos tickets de Bitácora GRM,
al estilo de Microsoft Project / Bitrix24 Gantt. Soporta los 4 tipos de
dependencias del estándar PMBOK:

    - FS (Finish-to-Start, Fin-Comienzo):   El sucesor NO puede comenzar
                                             hasta que el predecesor termine.
                                             Es el tipo por defecto en la
                                             mayoría de los diagramas Gantt.
    - SS (Start-to-Start,  Comienzo-Comienzo): El sucesor NO puede comenzar
                                             hasta que el predecesor
                                             comience.
    - FF (Finish-to-Finish, Fin-Fin):        El sucesor NO puede terminar
                                             hasta que el predecesor
                                             termine.
    - SF (Start-to-Finish, Comienzo-Fin):    El sucesor NO puede terminar
                                             hasta que el predecesor
                                             comience. (Es el más raro y
                                             generalmente se desaconseja;
                                             se incluye por paridad con
                                             MS Project / Bitrix24.)

Cada relación puede llevar un ``lag_dias`` (positivos = retraso,
negativos = adelanto) que ajusta la dependencia en días calendario.

Diseño:
    * ``predecesor_id`` y ``sucesor_id`` apuntan a ``tickets.id`` con
      ``ON DELETE CASCADE``: si se borra un ticket, sus dependencias
      desaparecen sin dejar huérfanos.
    * Constraint ``uq_dep`` que impide duplicar el mismo par
      (predecesor, sucesor, tipo): si el usuario intenta crear dos
      veces la misma dependencia, falla con IntegrityError.
    * Índices en ambos FKs para que las queries del Gantt (que filtran
      por "todas las dependencias que tienen X como sucesor" y
      viceversa) sean O(log N).
    * Constraint de validación en Python (método ``validar_orientacion``)
      para impedir dependencias circulares antes de tocar la BD.

Auditoría:
    Al igual que el resto del modelo, los cambios se registran en la
    tabla ``auditoria`` desde el servicio (``TicketDependenciaService``).
    Esta tabla NO tiene timestamps automáticos porque la información
    relevante para Gantt es la ``fecha_inicio`` y ``fecha_vencimiento_sla``
    del ticket (las maneja Ticket directamente).
"""
from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint, Column, Enum, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class TipoDependencia(str, enum.Enum):
    """Tipos de dependencia Gantt (FS / SS / FF / SF).

    El ``.value`` es lowercase para alinearse con el resto de enums del
    proyecto (TipoIncidencia, Prioridad, etc.).
    """
    FS = "fs"   # Finish-to-Start  (Fin → Comienzo)  [default]
    SS = "ss"   # Start-to-Start   (Comienzo → Comienzo)
    FF = "ff"   # Finish-to-Finish (Fin → Fin)
    SF = "sf"   # Start-to-Finish  (Comienzo → Fin)


# Catálogo legible (UI) de los tipos de dependencia
TIPO_DEPENDENCIA_NOMBRES = {
    TipoDependencia.FS: "Fin → Inicio (FS)",
    TipoDependencia.SS: "Inicio → Inicio (SS)",
    TipoDependencia.FF: "Fin → Fin (FF)",
    TipoDependencia.SF: "Inicio → Fin (SF)",
}


class TicketDependencia(Base):
    """Dependencia Gantt entre dos tickets.

    Una fila expresa: "el ticket ``sucesor_id`` depende del ticket
    ``predecesor_id`` con la regla ``tipo`` y un retraso de
    ``lag_dias`` días calendario".

    Atributos:
        predecesor (Ticket):   Ticket "anterior" en la cadena.
        sucesor (Ticket):      Ticket que depende del predecesor.
        tipo (TipoDependencia): Regla de dependencia Gantt.
        lag_dias (int):        Retraso (positivo) o adelanto (negativo)
                               en días calendario. ``0`` por defecto.
        nota (str):            Comentario libre (ej: "esperando QA").
    """
    __tablename__ = "ticket_dependencias"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # FKs: ambas con CASCADE para evitar huérfanos si se borra un ticket.
    predecesor_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sucesor_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    tipo = Column(
        Enum(TipoDependencia),
        default=TipoDependencia.FS,
        nullable=False,
    )
    lag_dias = Column(Integer, default=0, nullable=False)
    nota = Column(Text, nullable=True)

    # Relaciones: ambos lados apuntan al modelo Ticket. ``backref`` no se
    # usa para evitar ciclos en la importación (los tickets importan
    # ``ticket_dependencias`` indirectamente vía este módulo).
    predecesor = relationship(
        "Ticket",
        foreign_keys=[predecesor_id],
        backref="dependencias_salientes",
    )
    sucesor = relationship(
        "Ticket",
        foreign_keys=[sucesor_id],
        backref="dependencias_entrantes",
    )

    __table_args__ = (
        # No permitir duplicados: (pred, suc, tipo) es único.
        UniqueConstraint(
            "predecesor_id", "sucesor_id", "tipo",
            name="uq_dep_pred_suc_tipo",
        ),
        # Lags razonables: ±365 días (1 año). Más allá es claramente
        # un error de captura. CHECK funciona en PostgreSQL y SQLite ≥ 3.32.
        CheckConstraint(
            "lag_dias BETWEEN -365 AND 365",
            name="ck_dep_lag_rango",
        ),
        # Índices explícitos redundantes con los FK pero hacen explícita
        # la intención y permiten optimizaciones en queries del Gantt.
        Index("ix_dep_pred", "predecesor_id"),
        Index("ix_dep_suc", "sucesor_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<TicketDependencia pred={self.predecesor_id} "
            f"suc={self.sucesor_id} tipo={self.tipo.value} "
            f"lag={self.lag_dias}>"
        )

    @property
    def tipo_nombre_legible(self) -> str:
        """Devuelve la descripción humana del tipo (ej: 'Fin → Inicio (FS)')."""
        return TIPO_DEPENDENCIA_NOMBRES.get(self.tipo, self.tipo.value)

    @staticmethod
    def validar_orientacion(pred_id: int, suc_id: int) -> Optional[str]:
        """Valida que la orientación del enlace tenga sentido.

        Reglas:
            1. Los IDs deben ser distintos (no se puede depender de sí mismo).
            2. Ambos IDs deben ser positivos.
            3. En la app no validamos ciclos indirectos aquí: el servicio
               (``TicketDependenciaService.crear``) hace un BFS para
               detectar ciclos (A→B→C→A) ANTES de persistir.

        Returns:
            None si todo OK; str con el motivo del rechazo si no.
        """
        if pred_id is None or suc_id is None:
            return "Predecesor y sucesor son obligatorios."
        if pred_id == suc_id:
            return "Un ticket no puede depender de sí mismo."
        if pred_id <= 0 or suc_id <= 0:
            return "Los IDs deben ser positivos."
        return None
