"""
Modelo Ticket (Incidencia) y su historial de cambios de estado.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Enum, Index, DateTime, Table, Boolean
)
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base, TimestampMixin


# Tabla de asociación muchos-a-muchos: usuarios miembros de un ticket
ticket_miembros = Table(
    "ticket_miembros",
    Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", String(50), nullable=True),
)


class Prioridad(str, enum.Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class TipoIncidencia(str, enum.Enum):
    INCIDENCIA = "incidencia"
    SOLICITUD = "solicitud"
    CAMBIO = "cambio"
    PROBLEMA = "problema"


class Ticket(Base, TimestampMixin):
    """Incidencia del sistema (Tarjeta del Kanban)."""
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(20), unique=True, nullable=False, index=True)
    titulo = Column(String(200), nullable=False, index=True)
    descripcion = Column(Text, nullable=False)
    tipo = Column(
        Enum(TipoIncidencia), default=TipoIncidencia.INCIDENCIA, nullable=False, index=True
    )
    prioridad = Column(
        Enum(Prioridad), default=Prioridad.MEDIA, nullable=False, index=True
    )

    # Estado actual y FKs de gestión
    estado_id = Column(
        Integer, ForeignKey("estados.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    creador_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    asignado_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    # Catálogo dinámico del que proviene (JSON serializado)
    catalogo_tipo_id = Column(
        Integer, ForeignKey("catalogo_tipos.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Tablero al que pertenece (para soportar múltiples tableros en la app)
    tablero_id = Column(
        Integer, ForeignKey("tableros.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Datos dinámicos del catálogo (almacenados como JSON serializado)
    datos_catalogo = Column(Text, nullable=True)

    # SLA
    fecha_vencimiento_sla = Column(DateTime, nullable=True, index=True)
    sla_cumplido = Column(Integer, default=1, nullable=False)  # 1=True, 0=False, -1=pendiente

    # === Metadatos extendidos estilo Trello ===
    # Fecha de inicio planificada
    fecha_inicio = Column(DateTime, nullable=True, index=True)
    # Fecha de completado (cuando se marca como cerrado/resuelto)
    fecha_completado = Column(DateTime, nullable=True, index=True)
    # Si la fecha de vencimiento se cumplió
    fecha_cumplida = Column(Boolean, default=False, nullable=False)
    # Portada: color sólido o ID de un adjunto para usar como imagen
    portada_color = Column(String(20), nullable=True)
    portada_adjunto_id = Column(
        Integer, ForeignKey("adjuntos.id", ondelete="SET NULL"),
        nullable=True
    )
    # Si la descripción está en formato Markdown
    descripcion_md = Column(Boolean, default=False, nullable=False)
    # Posición de la tarjeta dentro de la lista (para orden manual)
    posicion = Column(Integer, default=0, nullable=False, index=True)
    # Si la tarjeta está archivada
    archivado = Column(Boolean, default=False, nullable=False, index=True)

    # Relaciones
    estado = relationship("Estado", back_populates="tickets", lazy="joined")
    creador = relationship(
        "Usuario", back_populates="tickets_creados",
        foreign_keys=[creador_id], lazy="joined"
    )
    asignado = relationship(
        "Usuario", back_populates="tickets_asignados",
        foreign_keys=[asignado_id], lazy="joined"
    )
    catalogo_tipo = relationship("CatalogoTipo", back_populates="tickets")
    tablero = relationship("Tablero", back_populates="tickets")
    portada_adjunto = relationship("Adjunto", foreign_keys=[portada_adjunto_id])
    historial_estados = relationship(
        "HistorialEstado",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="HistorialEstado.fecha.desc()",
    )
    auditorias = relationship(
        "Auditoria",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="Auditoria.created_at.desc()",
    )
    # === Relaciones de funcionalidades estilo Trello ===
    etiquetas = relationship(
        "Etiqueta",
        secondary="ticket_etiquetas",
        back_populates="tickets",
    )
    # Miembros múltiples (asignación adicional sin reemplazar al principal)
    miembros = relationship(
        "Usuario",
        secondary=ticket_miembros,
        backref="tickets_como_miembro",
    )
    checklists = relationship(
        "Checklist",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="Checklist.orden",
    )
    comentarios = relationship(
        "Comentario",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="Comentario.created_at.desc()",
    )
    adjuntos = relationship(
        "Adjunto",
        back_populates="ticket",
        foreign_keys="Adjunto.ticket_id",
        cascade="all, delete-orphan",
        order_by="Adjunto.created_at.desc()",
    )

    @property
    def total_comentarios(self) -> int:
        return len(self.comentarios) if self.comentarios else 0

    @property
    def total_adjuntos(self) -> int:
        return len(self.adjuntos) if self.adjuntos else 0

    @property
    def total_checklists(self) -> int:
        return len(self.checklists) if self.checklists else 0

    @property
    def progreso_checklists(self) -> dict:
        """Progreso agregado de todas las checklists del ticket."""
        total = 0
        completados = 0
        for c in (self.checklists or []):
            prog = c.progreso
            total += prog["total"]
            completados += prog["completados"]
        porcentaje = (completados / total * 100) if total > 0 else 0
        return {"total": total, "completados": completados, "porcentaje": round(porcentaje, 1)}

    @property
    def estado_sla_visual(self) -> str:
        """Devuelve el color del estado de SLA: verde (cumplido), rojo (vencido), ámbar (pendiente)."""
        if self.sla_cumplido == 1:
            return "cumplido"
        if self.sla_cumplido == 0:
            return "vencido"
        return "pendiente"

    @property
    def tiene_portada(self) -> bool:
        return bool(self.portada_color or self.portada_adjunto_id)

    @property
    def total_miembros(self) -> int:
        return len(self.miembros) if self.miembros else 0

    __table_args__ = (
        Index("ix_ticket_estado_prioridad", "estado_id", "prioridad"),
    )

    def __repr__(self) -> str:
        return f"<Ticket {self.codigo} - {self.titulo[:30]}>"


class HistorialEstado(Base):
    """Registro inmutable de cada cambio de estado de un ticket."""
    __tablename__ = "historial_estados"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    estado_origen_id = Column(
        Integer, ForeignKey("estados.id", ondelete="RESTRICT"), nullable=True
    )
    estado_destino_id = Column(
        Integer, ForeignKey("estados.id", ondelete="RESTRICT"), nullable=False
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    comentario = Column(Text, nullable=True)
    # IP/host desde donde se hizo el cambio
    origen = Column(String(200), nullable=True)
    fecha = Column(DateTime, nullable=False, index=True)

    ticket = relationship("Ticket", back_populates="historial_estados")
    estado_origen = relationship("Estado", foreign_keys=[estado_origen_id])
    estado_destino = relationship("Estado", foreign_keys=[estado_destino_id])
    usuario = relationship("Usuario")
