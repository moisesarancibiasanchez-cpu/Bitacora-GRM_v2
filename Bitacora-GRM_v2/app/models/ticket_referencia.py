"""
Modelo ``TicketReferencia`` — FEATURE 5: Referencias Internas entre tickets.

Permite vincular un ticket a otro con un ``tipo`` semántico y una ``nota``
opcional. A diferencia de ``TicketDependencia`` (que modela PRECEDENCIA
temporal para Gantt con tipos FS/SS/FF/SF + lag), ``TicketReferencia``
modela relaciones CONTEXTUALES simétricas (o etiquetadas) — equivalentes
a las "issue links" de Jira ("relates to", "duplicates", etc.).

Diferencias clave con ``TicketDependencia``:

+---------------------------+---------------------------+-----------------------------+
| Aspecto                   | TicketDependencia         | TicketReferencia            |
+===========================+===========================+=============================+
| Semántica                 | Precedencia temporal      | Relación contextual         |
+===========================+===========================+=============================+
| Direccionalidad           | predecesor → sucesor      | origen ↔ referenciado       |
+===========================+===========================+=============================+
| Tipos                     | FS, SS, FF, SF            | relacionado, duplicado,     |
|                           |                           | padre, hijo,                |
|                           |                           | bloquea, bloqueado_por      |
+===========================+===========================+=============================+
| Atributos extra           | lag_dias                  | nota (texto libre)          |
+===========================+===========================+=============================+
| Uso                       | Calcular fechas críticas  | Encontrar tickets           |
|                           | en Gantt                  | relacionados/contextuales   |
+===========================+===========================+=============================+
| Visibilidad en UI         | Flechas en Gantt          | Lista/badges en modal       |
+===========================+===========================+=============================+
"""
from __future__ import annotations

import enum
from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class TipoReferencia(str, enum.Enum):
    """Tipos de relación contextual entre tickets.

    - ``RELACIONADO``      → genérico, "está relacionado con" (default)
    - ``DUPLICADO``        → mismo problema reportado en otro ticket
    - ``PADRE``            → este ticket es subtarea del referenciado
    - ``HIJO``             → este ticket es padre del referenciado
    - ``BLOQUEA``          → este ticket bloquea al referenciado
    - ``BLOQUEADO_POR``    → este ticket está bloqueado por el referenciado
    """
    RELACIONADO = "relacionado"
    DUPLICADO = "duplicado"
    PADRE = "padre"
    HIJO = "hijo"
    BLOQUEA = "bloquea"
    BLOQUEADO_POR = "bloqueado_por"


# Mapeo inverso: tipo simétrico ↔ tipo "reflejado" para evitar duplicados.
# Ej: si A → B es "padre", entonces B → A ya está cubierto por "hijo" (no
# se inserta como relación adicional). Esto reduce ruido en la BD y permite
# la consulta bidireccional automática.
TIPO_INVERSO = {
    TipoReferencia.RELACIONADO: TipoReferencia.RELACIONADO,
    TipoReferencia.DUPLICADO: TipoReferencia.DUPLICADO,
    TipoReferencia.PADRE: TipoReferencia.HIJO,
    TipoReferencia.HIJO: TipoReferencia.PADRE,
    TipoReferencia.BLOQUEA: TipoReferencia.BLOQUEADO_POR,
    TipoReferencia.BLOQUEADO_POR: TipoReferencia.BLOQUEA,
}


class TicketReferencia(Base):
    """Vinculación contextual entre dos tickets (m2m self-referential).

    Modelo simétrico: si A referencia a B, al consultar "referencias
    del ticket A" se devuelve B; al consultar "referencias del ticket B"
    también aparece A (porque la consulta se hace en ambos sentidos).
    Ver ``TicketReferenciaService.listar_para_ticket``.

    Constraints:
    - ``uq_orig_dest_tipo`` : no se permite duplicar la misma tripla
      (origen, destino, tipo). Esto evita INSERT redundantes pero NO
      impide tener dos referencias distintas entre los mismos tickets
      si el ``tipo`` difiere (ej: A→B como "duplicado" Y A→B como
      "padre" — son relaciones semánticas diferentes).
    - ``ck_no_self_ref``    : un ticket no puede referenciarse a sí mismo.
    """
    __tablename__ = "ticket_referencias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_origen_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket_referenciado_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo = Column(
        Enum(TipoReferencia, name="tiporeferencia", native_enum=False, length=20),
        nullable=False,
        default=TipoReferencia.RELACIONADO,
    )
    nota = Column(Text, nullable=True)
    creado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    # === Relaciones ===
    ticket_origen = relationship(
        "Ticket",
        foreign_keys=[ticket_origen_id],
        backref="referencias_salientes",
    )
    ticket_referenciado = relationship(
        "Ticket",
        foreign_keys=[ticket_referenciado_id],
        backref="referencias_entrantes",
    )
    creado_por = relationship("Usuario")

    # === Constraints ===
    __table_args__ = (
        UniqueConstraint(
            "ticket_origen_id", "ticket_referenciado_id", "tipo",
            name="uq_ref_orig_dest_tipo",
        ),
        CheckConstraint(
            "ticket_origen_id != ticket_referenciado_id",
            name="ck_ref_no_self_ref",
        ),
        Index("ix_ref_origen_tipo", "ticket_origen_id", "tipo"),
        Index("ix_ref_destino_tipo", "ticket_referenciado_id", "tipo"),
    )

    def __repr__(self) -> str:
        return (
            f"<TicketReferencia id={self.id} "
            f"origen={self.ticket_origen_id} "
            f"destino={self.ticket_referenciado_id} "
            f"tipo={self.tipo!r}>"
        )

    def to_dict(self) -> dict:
        """Serializa a dict (uso interno: serialización JSON / templates)."""
        return {
            "id": self.id,
            "ticket_origen_id": self.ticket_origen_id,
            "ticket_referenciado_id": self.ticket_referenciado_id,
            "tipo": self.tipo.value if hasattr(self.tipo, "value") else str(self.tipo),
            "nota": self.nota,
            "creado_por_id": self.creado_por_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
