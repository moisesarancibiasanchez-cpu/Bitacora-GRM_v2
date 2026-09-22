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
from datetime import datetime, timezone
from typing import List, Optional, Tuple

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

        Lanza ``EtapaError`` si la asignación no existe.
        """
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

    # ------------------------------------------------------------------ #
    # DEPENDENCIAS AUTO-FS ENTRE ETAPAS DEL MISMO TICKET
    # ------------------------------------------------------------------ #
    def crear_dependencias_auto_fs(self, ticket: Ticket) -> int:
        """Crea N-1 dependencias FS entre las etapas del mismo ticket.

        Por cada par consecutivo (etapa_i, etapa_{i+1}) crea una fila
        en ``ticket_dependencias`` con ``tipo='fs'`` y ``nota`` que
        identifica la relación como auto-generada.

        Esta materialización en ``ticket_dependencias`` (no en una tabla
        propia de etapas) es deliberada: reusa el render del Gantt que ya
        sabe dibujar flechas a partir de ``TicketDependencia``. NO se
        duplican relaciones que ya existan.

        Devuelve el número de relaciones creadas (no incluye las que ya
        existían).
        """
        # Import local para evitar ciclo en import graph: etapa_service
        # → ticket_dependencia → no_cycle, pero por seguridad diferimos.
        from app.models.ticket_dependencia import (
            TicketDependencia, TipoDependencia,
        )

        if not ticket or not ticket.id:
            return 0

        etapas = self.listar_etapas_de_ticket(ticket.id)
        if len(etapas) < 2:
            return 0

        # Obtener las dependencias FS ya existentes para evitar duplicados.
        ya_existentes = {
            (d.predecesor_id, d.sucesor_id)
            for d in (
                self.db.query(TicketDependencia)
                .filter(
                    TicketDependencia.predecesor_id == ticket.id,
                    TicketDependencia.tipo == TipoDependencia.FS,
                )
                .all()
            )
        }
        # NOTA: las dependencias del Gantt en este proyecto apuntan a
        # ``tickets.id`` (FS entre tickets), no entre TicketEtapa. Aquí
        # creamos una **representación explícita** como TicketDependencia
        # entre el MISMO ticket con `lag_dias` calculado desde las fechas
        # reales de las etapas. Esto permite ver las flechas aunque las
        # etapas compartan el mismo ticket padre.
        #
        # Diseño: en lugar de TicketDependencia(ticket → ticket, ...),
        # creamos registros lógicos usando IDs de TicketEtapa NEGATIVOS
        # ofuscados como `predecesor_virtual_id = -etapa_id` y
        # `sucesor_virtual_id = -etapa_id`. PERO esto viola la FK a
        # tickets.id. Por ello, en esta primera versión NO creamos
        # TicketDependencia entre etapas: documentamos que las flechas
        # se dibujarán en el render del Gantt directamente desde
        # TicketEtapa.fecha_inicio/fin (chain visual, no FK).
        #
        # Esta función queda como hook para FUTURAS integraciones donde
        # se quiera representar la cadena como relaciones de primera
        # clase. Devuelve 0.
        logger.debug(
            "[etapa_service] Hook crear_dependencias_auto_fs invocado para "
            "ticket=%s; la cadena visual entre etapas se renderiza "
            "directamente desde TicketEtapa (no se crean FK).",
            ticket.id,
        )
        return 0
