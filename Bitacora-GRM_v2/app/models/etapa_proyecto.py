"""
Modelo EtapaProyecto + TicketEtapa (FEATURE: Sub-bars de etapas en Gantt).

Permite modelar las fases del ciclo de vida UAT del proyecto (Medición de
Esfuerzo, Análisis, Desarrollo, Pruebas, etc.) como un catálogo editable
y asignar a cada ticket sus 10 etapas con fechas de inicio/fin propias.

Cada ``TicketEtapa`` representa "la etapa X del ticket Y tiene inicio en
fecha A y fin en fecha B". El Gantt las dibuja como sub-barras dentro de
la fila del ticket (modo expandido) o como dots de progreso (modo
compacto, ahora sustituido por la barra coloreada según etapa actual).

Auto-FS (Fin → Inicio): por defecto cada etapa N+1 depende de la etapa N
del mismo ticket. Esto se materializa en filas de ``TicketDependencia``
para que las flechas aparezcan gratis en el Gantt.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class EtapaProyecto(Base, TimestampMixin):
    """Catálogo de las fases del proyecto UAT.

    Seed inicial (idempotente en ``app/db/migrations.py``):
        1  ESFUERZO     — Medición de Esfuerzo
        2  ANALISIS     — Análisis, Revisión y Aprobación
        3  DESARROLLO   — Desarrollo
        4  PRUEBAS_INT  — Pruebas Internas
        5  ENTREGA_QA   — Entrega y despliegue en QA
        6  INDUCCION    — Inducción de HU
        7  PRUEBAS_C1   — Ejecución de pruebas ciclo 1
        8  REV_UAT      — Reuniones de Revisión UAT
        9  CORRECC      — Correcciones y despliegue
        10 PRUEBAS_C2   — Ejecución de pruebas ciclo 2

    Atributos:
        codigo (str): Slug único en MAYÚSCULAS (ej. ``"DESARROLLO"``).
        nombre (str): Etiqueta legible que se muestra en la UI.
        orden (int): Posición dentro del flujo (1..N). El seed usa 1..10.
        color (str): Color HEX (ej. ``"#06b6d4"``) usado por el Gantt.
        activo (bool): ``False`` para ocultar etapas del catálogo de UI
                       sin romper FKs de ``ticket_etapas`` ya creadas.
    """
    __tablename__ = "etapas_proyecto"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(40), unique=True, nullable=False, index=True)
    nombre = Column(String(120), nullable=False)
    orden = Column(Integer, nullable=False, index=True)
    color = Column(String(7), nullable=False, default="#6366f1")
    activo = Column(Integer, nullable=False, default=1)  # 1=sí, 0=no

    # Relación inversa: las asignaciones de esta etapa a tickets
    ticket_etapas = relationship(
        "TicketEtapa", back_populates="etapa", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("orden", name="uq_etapa_orden"),
        CheckConstraint("activo IN (0, 1)", name="ck_etapa_activo"),
    )

    def __repr__(self) -> str:
        return f"<EtapaProyecto {self.codigo} orden={self.orden}>"


class TicketEtapa(Base, TimestampMixin):
    """Asignación de una etapa a un ticket con sus fechas concretas.

    Una fila expresa: "el ticket ``ticket_id`` tiene la etapa
    ``etapa_id`` con inicio en ``fecha_inicio`` y fin en ``fecha_fin``".

    Si ``fecha_inicio`` o ``fecha_fin`` son NULL, la etapa todavía no se
    ha planificado (aparece como círculo vacío en el Gantt expandido).

    El constraint ``uq_ticket_etapa`` impide duplicar la misma etapa
    para un mismo ticket (cada combinación ticket-etapa es única).

    Diseño:
        * Ambas FK usan ``ON DELETE CASCADE``: si se borra el ticket o
          la etapa, las asignaciones desaparecen sin huérfanos.
        * ``_virtual_id`` en el Gantt se construye como
          ``f"TE-{ticket_id}-{etapa_id}"`` para que las dependencias
          entre etapas puedan apuntar a "este ticket virtual" como si
          fuera una barra más del Gantt.
    """
    __tablename__ = "ticket_etapas"

    id = Column(Integer, primary_key=True, autoincrement=True)

    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    etapa_id = Column(
        Integer,
        ForeignKey("etapas_proyecto.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Fechas planificadas / reales (NULL = aún no planificada).
    fecha_inicio = Column(String(10), nullable=True)   # "YYYY-MM-DD"
    fecha_fin = Column(String(10), nullable=True)      # "YYYY-MM-DD"

    # Si ya se marcó como completada (independiente de las fechas).
    completado = Column(Integer, nullable=False, default=0)  # 0=no, 1=sí

    # Orden dentro del ticket (lo define la posición de la etapa
    # en el catálogo pero se persiste por flexibilidad).
    orden = Column(Integer, nullable=False, default=0, index=True)

    # Nota libre (qué hizo falta en esta etapa, link a PR, build, etc.)
    notas = Column(Text, nullable=True)

    # Relaciones
    etapa = relationship("EtapaProyecto", back_populates="ticket_etapas")
    # ticket se referencia vía backref declarado en app.models.ticket cuando
    # se integre este módulo; aquí lo declaramos lazy="select" para evitar
    # ciclos en la importación.

    __table_args__ = (
        UniqueConstraint("ticket_id", "etapa_id", name="uq_ticket_etapa"),
        CheckConstraint("completado IN (0, 1)", name="ck_te_completado"),
        # NOTA: los índices de las FKs ya los crea ``Column(..., index=True)``
        # en las definiciones de ``ticket_id`` y ``etapa_id``. Evitamos
        # duplicarlos aquí para no inflar el catálogo de Postgres con
        # pares idénticos bajo nombres distintos.
    )

    def __repr__(self) -> str:
        return (
            f"<TicketEtapa ticket={self.ticket_id} etapa={self.etapa_id} "
            f"{self.fecha_inicio}→{self.fecha_fin} ok={self.completado}>"
        )

    @property
    def is_planned(self) -> bool:
        """True si tiene fecha_inicio planificada (no necesariamente fin)."""
        return bool(self.fecha_inicio)

    @property
    def is_done(self) -> bool:
        """True si está marcada como completada."""
        return bool(self.completado)
