"""
EtapaService — Servicio de negocio para FEATURE 4 (Sub-bars de etapas en Gantt).

Encapsula la lógica de:
- Listar / crear / editar el catálogo de etapas del proyecto.
- Asignar automáticamente las 10 etapas a un ticket al crearlo.
- Actualizar las fechas de una etapa de un ticket.
- Crear / eliminar las dependencias FS entre etapas del mismo ticket
  (auto-FS) cuando se solicita.

NO participa en transiciones de estado del Kanban ni en SLA. Su único
punto de contacto con el modelo ``Ticket`` es la auto-asignación al
crear un ticket nuevo, vía el hook ``asignar_etapas_iniciales``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.etapa_proyecto import EtapaProyecto, TicketEtapa
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)


class EtapaError(Exception):
    """Errores de validación al manipular etapas / asignaciones."""

    def __init__(self, mensaje: str, codigo: str = "etapa_invalida"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


class EtapaService:
    """Operaciones CRUD + lógica de etapas para tickets y catálogo UAT."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # CATÁLOGO
    # ------------------------------------------------------------------ #
    def listar_etapas(self, solo_activas: bool = True) -> List[EtapaProyecto]:
        """Devuelve el catálogo ordenado por ``orden`` ascendente."""
        q = self.db.query(EtapaProyecto).order_by(EtapaProyecto.orden.asc())
        if solo_activas:
            q = q.filter(EtapaProyecto.activo == 1)  # noqa: E712
        return q.all()

    def obtener_etapa(self, etapa_id: int) -> Optional[EtapaProyecto]:
        return self.db.query(EtapaProyecto).filter(
            EtapaProyecto.id == etapa_id
        ).first()

    def obtener_por_codigo(self, codigo: str) -> Optional[EtapaProyecto]:
        return self.db.query(EtapaProyecto).filter(
            EtapaProyecto.codigo == codigo
        ).first()

    # ------------------------------------------------------------------ #
    # ASIGNACIÓN AUTOMÁTICA INICIAL
    # ------------------------------------------------------------------ #
    def asignar_etapas_iniciales(self, ticket: Ticket) -> List[TicketEtapa]:
        """Crea 10 ``TicketEtapa`` (una por etapa del catálogo) para un
        ticket nuevo. Idempotente: si ya existen, no duplica.

        Pensado para invocarse en el ``TicketService.crear`` justo
        después del INSERT y antes del commit. Devuelve las filas creadas
        o, si ya existían, las existentes.
        """
        if not ticket or not ticket.id:
            return []

        etapas = self.listar_etapas(solo_activas=True)
        if not etapas:
            # Sin catálogo (BD sin seed): no hacemos nada y devolvemos lista vacía.
            return []

        existentes = (
            self.db.query(TicketEtapa)
            .filter(TicketEtapa.ticket_id == ticket.id)
            .all()
        )
        existentes_etapa_ids = {te.etapa_id for te in existentes}
        ya_hay = bool(existentes)
        # Si ya hay asignaciones previas, no tocamos nada (idempotente).
        # Devolvemos las existentes para que el llamador pueda operar con ellas.
        if ya_hay:
            return existentes

        # Crear una fila por etapa, sin planificar (fechas NULL).
        nuevas: List[TicketEtapa] = []
        for e in etapas:
            te = TicketEtapa(
                ticket_id=ticket.id,
                etapa_id=e.id,
                orden=e.orden,
                fecha_inicio=None,
                fecha_fin=None,
                completado=0,
                notas=None,
            )
            self.db.add(te)
            nuevas.append(te)
        try:
            self.db.flush()  # para que tengan ID sin commit
        except IntegrityError as e:
            self.db.rollback()
            # Si por una carrera ya se crearon (caso extremo de doble click),
            # las recargamos y devolvemos.
            logger.warning(
                "[etapa_service] IntegrityError al asignar etapas iniciales "
                "al ticket %s: %s — reintentando lectura.",
                ticket.id, e,
            )
            return (
                self.db.query(TicketEtapa)
                .filter(TicketEtapa.ticket_id == ticket.id)
                .order_by(TicketEtapa.orden.asc())
                .all()
            )
        return nuevas

    # ------------------------------------------------------------------ #
    # LISTADO / EDICIÓN POR TICKET
    # ------------------------------------------------------------------ #
    def listar_etapas_de_ticket(self, ticket_id: int) -> List[TicketEtapa]:
        """Devuelve las etapas de un ticket ordenadas por ``orden``.

        Cada ``TicketEtapa`` viene con ``etapa`` eagerly-loaded (para
        que la UI pueda leer nombre/color sin N+1).
        """
        from sqlalchemy.orm import joinedload
        return (
            self.db.query(TicketEtapa)
            .options(joinedload(TicketEtapa.etapa))
            .filter(TicketEtapa.ticket_id == ticket_id)
            .order_by(TicketEtapa.orden.asc())
            .all()
        )

    def listar_etapas_para_tickets(
        self, ticket_ids: List[int]
    ) -> List[TicketEtapa]:
        """Devuelve TODAS las ``TicketEtapa`` cuyos tickets están en
        ``ticket_ids``. Pensado para alimentar el Gantt con un único
        round-trip a la BD.
        """
        from sqlalchemy.orm import joinedload
        if not ticket_ids:
            return []
        return (
            self.db.query(TicketEtapa)
            .options(joinedload(TicketEtapa.etapa))
            .filter(TicketEtapa.ticket_id.in_(ticket_ids))
            .order_by(
                TicketEtapa.ticket_id.asc(),
                TicketEtapa.orden.asc(),
            )
            .all()
        )

    def actualizar_etapa_ticket(
        self,
        ticket_id: int,
        etapa_id: int,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        completado: Optional[bool] = None,
        notas: Optional[str] = None,
    ) -> TicketEtapa:
        """Actualiza los campos editables de una asignación.

        - ``fecha_inicio`` / ``fecha_fin``: strings ``"YYYY-MM-DD"`` o
          ``None`` para dejar en blanco.
        - ``completado``: bool (True → 1, False → 0).
        - ``notas``: texto libre; ``""`` se normaliza a ``None``.

        Lanza ``EtapaError`` si la asignación no existe o si las fechas
        son inválidas (formato o ``fecha_fin < fecha_inicio``).
        """
        # Validación de fechas: las parseamos una sola vez y validamos
        # que fecha_fin >= fecha_inicio. Esto evita estados ilógicos en
        # el Gantt (flechas hacia atrás).
        try:
            fi = self._parse_fecha(fecha_inicio) if fecha_inicio else None
        except ValueError as e:
            raise EtapaError(
                f"fecha_inicio inválida ({fecha_inicio}): {e}",
                codigo="fecha_inicio_invalida",
            ) from e
        try:
            ff = self._parse_fecha(fecha_fin) if fecha_fin else None
        except ValueError as e:
            raise EtapaError(
                f"fecha_fin inválida ({fecha_fin}): {e}",
                codigo="fecha_fin_invalida",
            ) from e
        if fi and ff and ff < fi:
            raise EtapaError(
                f"fecha_fin ({fecha_fin}) no puede ser anterior a "
                f"fecha_inicio ({fecha_inicio}).",
                codigo="rango_fechas_invalido",
            )

        te = (
            self.db.query(TicketEtapa)
            .filter(
                TicketEtapa.ticket_id == ticket_id,
                TicketEtapa.etapa_id == etapa_id,
            )
            .first()
        )
        if not te:
            raise EtapaError(
                f"No existe asignación ticket={ticket_id} etapa={etapa_id}.",
                codigo="asignacion_no_encontrada",
            )

        if fecha_inicio is not None:
            te.fecha_inicio = fecha_inicio or None
        if fecha_fin is not None:
            te.fecha_fin = fecha_fin or None
        if completado is not None:
            te.completado = 1 if completado else 0
        if notas is not None:
            te.notas = (notas or "").strip() or None

        try:
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            raise EtapaError(
                f"Error de integridad al actualizar etapa: {e.orig}",
                codigo="integridad",
            ) from e
        self.db.refresh(te)
        return te

    @staticmethod
    def _parse_fecha(s: str) -> Optional[datetime]:
        """Convierte ``"YYYY-MM-DD"`` a ``datetime`` (a medianoche) o
        lanza ``ValueError`` si el formato es inválido.
        """
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise ValueError(f"formato esperado YYYY-MM-DD, recibido {s!r}")

    # ------------------------------------------------------------------ #
    # DEPENDENCIAS AUTO-FS ENTRE ETAPAS DEL MISMO TICKET
    # ------------------------------------------------------------------ #
    # NOTA DE DISEÑO: las flechas auto-FS entre etapas del mismo ticket
    # se renderizan DIRECTAMENTE desde ``TicketEtapa.fecha_inicio/fin``
    # en el frontend (ver ``app/templates/vistas/gantt.html``), sin
    # materializarse como filas en ``ticket_dependencias``.
    #
    # Motivo: ``ticket_dependencias.predecesor_id`` y ``sucesor_id``
    # apuntan a ``tickets.id`` (FS entre tickets, no entre etapas del
    # mismo ticket). Crear registros ahí requeriría o bien romper la FK
    # o bien ofuscar IDs negativos, ninguno aceptable. Por lo tanto la
    # cadena visual se dibuja en el render del Gantt y este hook queda
    # **explícitamente deshabilitado**.
    #
    # Si en el futuro se quiere modelar la cadena como relaciones de
    # primera clase, se necesitará una tabla ``ticket_etapa_dependencias``
    # propia con FKs a ``ticket_etapas.id``.
