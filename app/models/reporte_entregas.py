"""
Modelos para el sistema de Reporte Diario de Entregas.

El reporte diario de entregas es un correo que se envía al final del día
con la lista de tickets que entraron en un estado de "entrega" durante
la jornada. La arquitectura es:

- ``ReportePlantilla`` (singleton, fila clave=1):
    Almacena el contenido editable del correo (asunto, body html, body
    texto plano, firma, activo) y un flag global ``habilitado``.
    Solo existe UNA fila activa (clave=1); cualquier actualización
    reemplaza la fila existente.

- ``ReporteDestinatario``:
    Lista de usuarios o direcciones de correo que reciben el reporte.
    Puede ser un usuario del sistema (``usuario_id``) o una dirección
    suelta (``email``). Tiene un flag ``activo`` para poder desactivar
    sin eliminar el registro (preserva histórico).

- ``ReporteEntregaDiaria``:
    Tabla de idempotencia: registra UNA fila por cada transición de un
    ticket a un estado ``es_entrega=True``. La clave única sobre
    ``historial_estado_id`` garantiza que la misma transición NO se
    registre dos veces (incluso si la tarea Celery se reintenta o si el
    mismo ticket entra varias veces al mismo estado — solo cuenta la
    primera transición).
    El reporte diario se arma como SELECT de esta tabla filtrado por
    ``fecha_entrega::date = CURRENT_DATE`` (o el día que se pida).

La combinación ``UNIQUE(historial_estado_id)`` en
``ReporteEntregaDiaria`` es la garantía central de idempotencia:
INSERT ... ON CONFLICT DO NOTHING permite que la tarea Celery se
reintente sin miedo a duplicados.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


# ===========================================================================
#  Plantilla del correo (singleton, fila clave=1)
# ===========================================================================
class ReportePlantilla(Base, TimestampMixin):
    """
    Plantilla editable del correo del reporte diario de entregas.

    Es un singleton: existe solo UNA fila con id=1 (la clave se asegura
    con UNIQUE constraint y la lógica de upsert en
    ``ReporteEntregasService``). Los placeholders soportados en
    ``asunto`` / ``cuerpo_html`` / ``cuerpo_texto`` son:

      - ``{{fecha}}``       → fecha del reporte (ej: "viernes 6 de octubre de 2026")
      - ``{{cantidad}}``    → número de entregas del día
      - ``{{tabla_html}}``  → bloque HTML con la tabla de entregas
      - ``{{tabla_texto}}`` → bloque de texto plano con la lista de entregas

    Atributos
    ---------
    id : int
        Siempre 1 (constraint de unicidad).
    habilitado : bool
        Si False, la tarea programada NO envía el correo (sigue
        registrando entregas para que el admin pueda ver el histórico).
    asunto : str
        Asunto por defecto. Admite placeholders.
    cuerpo_html : str
        Cuerpo HTML completo del correo (estructura + tabla). Admite
        placeholders.
    cuerpo_texto : str
        Cuerpo en texto plano (para clientes que no soporten HTML).
    firma : str
        Bloque de firma que se añade al final (después de la tabla).
    """
    __tablename__ = "reporte_plantilla"

    id = Column(Integer, primary_key=True, autoincrement=True)
    habilitado = Column(
        Boolean, default=True, nullable=False,
        doc="Si False, NO se envía el correo (sigue registrando).",
    )
    asunto = Column(
        String(255), nullable=False, default="",
        doc="Asunto del correo (admite {{fecha}} y {{cantidad}}).",
    )
    cuerpo_html = Column(
        Text, nullable=False, default="",
        doc="Cuerpo HTML completo del reporte (estructura + tabla).",
    )
    cuerpo_texto = Column(
        Text, nullable=False, default="",
        doc="Cuerpo en texto plano para clientes sin HTML.",
    )
    firma = Column(
        Text, nullable=True, default="",
        doc="Bloque de firma que se añade al final del correo.",
    )

    def __repr__(self) -> str:
        return f"<ReportePlantilla id={self.id} habilitado={self.habilitado}>"


# ===========================================================================
#  Destinatarios del reporte
# ===========================================================================
class ReporteDestinatario(Base, TimestampMixin):
    """
    Destinatario (usuario o email suelto) que recibe el reporte diario.

    Puede ser:
      - Un usuario del sistema (``usuario_id`` FK a usuarios.id): el correo
        se envía al ``email`` del usuario. Si el usuario se desactiva,
        se omite el envío.
      - Una dirección de correo suelta (``email``): útil para destinatarios
        externos al sistema (ej: gerencia, auditoría).

    En ambos casos el filtro activo es: ``activo=True AND
    (usuario IS NULL OR usuario.is_active=True)``.
    """
    __tablename__ = "reporte_destinatarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(
        String(160), nullable=False, index=True,
        doc="Dirección de correo destino (snapshot, no se recalcula).",
    )
    nombre = Column(
        String(120), nullable=True,
        doc="Nombre visible del destinatario (opcional, para mostrar en UI).",
    )
    rol = Column(
        String(40), nullable=True,
        doc="Etiqueta libre (ej: 'gerencia', 'auditoría', 'qa-lead').",
    )
    # Snapshot del rol del usuario al momento de agregarlo (opcional,
    # sirve para filtrar por rol sin JOIN a la tabla usuarios).
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True, index=True,
        doc="FK opcional al usuario del sistema (si viene del listado).",
    )
    activo = Column(
        Boolean, default=True, nullable=False, index=True,
        doc="Si False, NO se le envía el correo (se preserva histórico).",
    )
    notas = Column(
        Text, nullable=True,
        doc="Notas internas (no se envían en el correo).",
    )

    # Relación al usuario (para mostrar su nombre en la UI admin)
    usuario_obj = relationship(
        "Usuario",
        foreign_keys=[usuario_id],
    )

    def __repr__(self) -> str:
        return (
            f"<ReporteDestinatario id={self.id} email={self.email!r} "
            f"activo={self.activo}>"
        )


# ===========================================================================
#  Tabla de idempotencia del reporte (una fila por transición)
# ===========================================================================
class ReporteEntregaDiaria(Base, TimestampMixin):
    """
    Registro de UNA transición a un estado de entrega.

    Constraints de unicidad:
      - ``UNIQUE(historial_estado_id)`` → garantiza idempotencia:
        la misma transición NO se registra dos veces, aunque la tarea
        Celery se reintente.

    El reporte diario se arma con:
        SELECT * FROM reporte_entregas_diarias
        WHERE fecha_entrega::date = :fecha_objetivo
        ORDER BY fecha_entrega ASC

    Una vez que el reporte se genera y se envía, ``reporte_enviado_en``
    queda con timestamp; las entregas que aún no tienen ese campo
    (NULL) son las que faltan enviar en el reporte del día.
    """
    __tablename__ = "reporte_entregas_diarias"
    __table_args__ = (
        UniqueConstraint(
            "historial_estado_id",
            name="uq_reporte_entrega_historial",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # === FKs (NULL permitido solo si el ticket se borró después) ===
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True, index=True,
        doc="FK al ticket. NULL si el ticket fue eliminado (preserva histórico).",
    )
    historial_estado_id = Column(
        Integer, ForeignKey("historial_estados.id", ondelete="SET NULL"),
        nullable=True,
        doc=(
            "FK al registro de historial que disparó el evento. La "
            "UNIQUE sobre esta columna es la garantía de idempotencia."
        ),
    )
    estado_destino_id = Column(
        Integer, ForeignKey("estados.id", ondelete="SET NULL"),
        nullable=True, index=True,
        doc="Estado de entrega en el que cayó el ticket.",
    )
    usuario_cambio_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        doc="Usuario que ejecutó el cambio de estado.",
    )

    # === Snapshot al momento del cambio (para que el reporte NO se ===
    #     altere si luego se renombra el ticket o se reasigna)        ===
    ticket_codigo = Column(
        String(40), nullable=False,
        doc="Snapshot del código del ticket (ej: 'INC-042').",
    )
    ticket_titulo = Column(
        String(255), nullable=True,
        doc="Snapshot del título al momento del cambio.",
    )
    estado_destino_nombre = Column(
        String(80), nullable=False,
        doc="Snapshot del nombre del estado destino.",
    )
    asignado_email = Column(
        String(160), nullable=True,
        doc="Snapshot del email del asignado al momento del cambio.",
    )
    asignado_nombre = Column(
        String(160), nullable=True,
        doc="Snapshot del nombre del asignado al momento del cambio.",
    )

    # === Marca temporal ===
    fecha_entrega = Column(
        DateTime, nullable=False, index=True,
        doc="UTC timestamp de cuándo se ejecutó la transición.",
        server_default=func.now(),
    )

    # === Marca de envío del reporte diario ===
    reporte_enviado_en = Column(
        DateTime, nullable=True,
        doc=(
            "UTC timestamp en que se envió el reporte que contenía esta "
            "entrega. NULL = aún no se ha enviado en un reporte diario."
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ReporteEntregaDiaria id={self.id} ticket={self.ticket_codigo!r} "
            f"estado={self.estado_destino_nombre!r} fecha={self.fecha_entrega}>"
        )