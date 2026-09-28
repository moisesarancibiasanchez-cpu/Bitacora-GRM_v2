"""
TicketReferenciaService — Servicio de negocio para la FEATURE 5 (Referencias Internas).

Encapsula la lógica CRUD y de validación de referencias contextuales entre
tickets. A diferencia de ``TicketDependenciaService`` (que modela
precedencia temporal para Gantt), aquí modelamos relaciones CONTEXTUALES
simétricas (tipo "issue links" de Jira: relates to, duplicates, parent/child,
blocks/blocked-by).

Operaciones:
- ``agregar``        crea una referencia origen→destino (idempotente si ya
                     existe la misma tripla origen/destino/tipo).
- ``listar_para_ticket``  devuelve TODAS las referencias donde el ticket
                     participa como origen O como destino (consulta
                     bidireccional automática).
- ``eliminar``       elimina una referencia por ID.
- ``buscar_tickets_para_autocompletar``  helper para autocompletar el
                     selector de tickets en la UI (búsqueda por código o
                     título, excluyendo el ticket actual).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria
from app.models.ticket import Ticket
from app.models.ticket_referencia import (
    TIPO_INVERSO, TicketReferencia, TipoReferencia,
)

logger = logging.getLogger(__name__)


# Catálogo "humano" para mostrar en UI (no es obligatorio, sólo narrativo).
TIPO_REFERENCIA_NOMBRES = {
    TipoReferencia.RELACIONADO:   "Relacionado",
    TipoReferencia.DUPLICADO:     "Duplicado",
    TipoReferencia.PADRE:         "Es tarea hija de",
    TipoReferencia.HIJO:          "Es tarea padre de",
    TipoReferencia.BLOQUEA:       "Bloquea a",
    TipoReferencia.BLOQUEADO_POR: "Bloqueado por",
}


class ReferenciaError(Exception):
    """Errores de validación al crear/eliminar una referencia."""

    def __init__(self, mensaje: str, codigo: str = "referencia_invalida"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


class TicketReferenciaService:
    """Operaciones CRUD + validaciones para referencias internas."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # CREAR
    # ------------------------------------------------------------------ #
    def agregar(
        self,
        ticket_origen_id: int,
        ticket_referenciado_id: int,
        tipo: str = "relacionado",
        nota: Optional[str] = None,
        creado_por_id: Optional[int] = None,
    ) -> TicketReferencia:
        """Crea una nueva referencia entre dos tickets.

        Validaciones (en orden):
            1. IDs distintos y positivos (anti auto-referencia).
            2. ``tipo`` ∈ {relacionado, duplicado, padre, hijo,
               bloquea, bloqueado_por}.
            3. Ambos tickets existen.
            4. La tripla (origen, destino, tipo) NO existe ya.
            5. Inserta registro en ``auditoria``.

        Raises:
            ReferenciaError: con ``codigo`` específico según el motivo.
        """
        # 1) Orientación
        if (
            not isinstance(ticket_origen_id, int)
            or not isinstance(ticket_referenciado_id, int)
            or ticket_origen_id <= 0
            or ticket_referenciado_id <= 0
        ):
            raise ReferenciaError(
                "Los IDs de tickets deben ser enteros positivos.",
                codigo="ids_invalidos",
            )
        if ticket_origen_id == ticket_referenciado_id:
            raise ReferenciaError(
                "Un ticket no puede referenciarse a sí mismo.",
                codigo="auto_referencia",
            )

        # 2) Tipo
        try:
            tipo_enum = TipoReferencia(tipo)
        except ValueError:
            tipos_validos = ", ".join(t.value for t in TipoReferencia)
            raise ReferenciaError(
                f"Tipo '{tipo}' no válido. Use uno de: {tipos_validos}.",
                codigo="tipo_invalido",
            )

        # 3) Existencia
        origen = self.db.query(Ticket).filter(Ticket.id == ticket_origen_id).first()
        if not origen:
            raise ReferenciaError(
                f"El ticket origen (id={ticket_origen_id}) no existe.",
                codigo="origen_inexistente",
            )
        destino = self.db.query(Ticket).filter(Ticket.id == ticket_referenciado_id).first()
        if not destino:
            raise ReferenciaError(
                f"El ticket referenciado (id={ticket_referenciado_id}) no existe.",
                codigo="destino_inexistente",
            )

        # 4) Duplicado
        existe = (
            self.db.query(TicketReferencia)
            .filter(
                TicketReferencia.ticket_origen_id == ticket_origen_id,
                TicketReferencia.ticket_referenciado_id == ticket_referenciado_id,
                TicketReferencia.tipo == tipo_enum,
            )
            .first()
        )
        if existe:
            raise ReferenciaError(
                "Ya existe esa misma referencia entre los dos tickets.",
                codigo="duplicado",
            )

        # 5) Persistir
        ref = TicketReferencia(
            ticket_origen_id=ticket_origen_id,
            ticket_referenciado_id=ticket_referenciado_id,
            tipo=tipo_enum,
            nota=(nota.strip() if nota else None),
            creado_por_id=creado_por_id,
        )
        self.db.add(ref)
        try:
            self.db.flush()  # para tener ref.id antes del commit
        except IntegrityError as e:
            self.db.rollback()
            raise ReferenciaError(
                f"Error de integridad al crear la referencia: {e.orig}",
                codigo="integridad",
            )

        # 6) Auditoría (best-effort, no rompe si falla)
        try:
            valor_nuevo = {
                "tipo": tipo_enum.value,
                "ticket_referenciado_id": ticket_referenciado_id,
                "ticket_referenciado_codigo": destino.codigo,
                "nota": ref.nota,
            }
            auditoria = Auditoria(
                ticket_id=ticket_origen_id,
                usuario_id=creado_por_id,
                accion="referencia_agregada",
                valor_anterior=None,
                valor_nuevo=valor_nuevo,
                comentario=(
                    f"Referencia '{tipo_enum.value}' → ticket "
                    f"{destino.codigo} (id={destino.id})"
                ),
            )
            self.db.add(auditoria)
            self.db.commit()
        except Exception as e:  # noqa: BLE001
            # No romper el flujo principal si la auditoría falla.
            logger.warning(
                "[referencias] No se pudo registrar auditoría: %s", e,
            )
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

        self.db.refresh(ref)
        return ref

    # ------------------------------------------------------------------ #
    # LEER
    # ------------------------------------------------------------------ #
    def listar_para_ticket(self, ticket_id: int) -> List[dict]:
        """Devuelve TODAS las referencias donde ``ticket_id`` aparece como
        origen O como destino, con metadatos del ticket opuesto para que la
        UI pueda renderizar la lista sin un JOIN adicional.

        Retorna una lista de ``dict`` con la forma::

            {
                "id":              int,    # ID de la referencia
                "tipo":            str,    # tipo de la referencia
                "tipo_nombre":     str,    # nombre legible
                "direccion":       str,    # "saliente" | "entrante"
                "ticket_id":       int,    # ID del OTRO ticket (no el ticket actual)
                "ticket_codigo":   str,
                "ticket_titulo":   str,
                "ticket_estado":   str | None,
                "nota":            str | None,
                "creado_por_id":   int | None,
                "created_at":      datetime,
            }
        """
        if not ticket_id:
            return []

        # Hacemos un join con Ticket dos veces (origen y destino).
        from app.models.estado import Estado

        t_origen = Ticket.__table__.alias("t_origen")
        t_destino = Ticket.__table__.alias("t_destino")

        rows = (
            self.db.query(
                TicketReferencia,
                t_origen.c.codigo.label("origen_codigo"),
                t_origen.c.titulo.label("origen_titulo"),
                t_destino.c.codigo.label("destino_codigo"),
                t_destino.c.titulo.label("destino_titulo"),
            )
            .join(t_origen, t_origen.c.id == TicketReferencia.ticket_origen_id)
            .join(t_destino, t_destino.c.id == TicketReferencia.ticket_referenciado_id)
            .filter(
                or_(
                    TicketReferencia.ticket_origen_id == ticket_id,
                    TicketReferencia.ticket_referenciado_id == ticket_id,
                )
            )
            .order_by(TicketReferencia.created_at.desc())
            .all()
        )

        # Hidratamos los estados con un solo query (evita N+1).
        ticket_ids_a_resolver = set()
        for ref, oc, ot, dc, dt in rows:
            if ref.ticket_origen_id == ticket_id:
                ticket_ids_a_resolver.add(ref.ticket_referenciado_id)
            else:
                ticket_ids_a_resolver.add(ref.ticket_origen_id)

        estados_por_ticket: dict = {}
        if ticket_ids_a_resolver:
            estados_rows = (
                self.db.query(Ticket.id, Estado.nombre)
                .outerjoin(Estado, Estado.id == Ticket.estado_id)
                .filter(Ticket.id.in_(ticket_ids_a_resolver))
                .all()
            )
            estados_por_ticket = {tid: enombre for tid, enombre in estados_rows}

        resultado = []
        for ref, oc, ot, dc, dt in rows:
            if ref.ticket_origen_id == ticket_id:
                # Esta referencia SALE de mi ticket hacia otro
                ticket_id_opuesto = ref.ticket_referenciado_id
                ticket_codigo = dc
                ticket_titulo = dt
                direccion = "saliente"
            else:
                # Esta referencia ENTRA desde otro hacia mi ticket
                ticket_id_opuesto = ref.ticket_origen_id
                ticket_codigo = oc
                ticket_titulo = ot
                direccion = "entrante"

            tipo_val = ref.tipo.value if hasattr(ref.tipo, "value") else str(ref.tipo)
            resultado.append({
                "id": ref.id,
                "tipo": tipo_val,
                "tipo_nombre": TIPO_REFERENCIA_NOMBRES.get(ref.tipo, tipo_val),
                "direccion": direccion,
                "ticket_id": ticket_id_opuesto,
                "ticket_codigo": ticket_codigo or "?",
                "ticket_titulo": (ticket_titulo or "")[:120],
                "ticket_estado": estados_por_ticket.get(ticket_id_opuesto),
                "nota": ref.nota,
                "creado_por_id": ref.creado_por_id,
                "created_at": ref.created_at.isoformat() if ref.created_at else None,
            })
        return resultado

    def obtener(self, ref_id: int) -> Optional[TicketReferencia]:
        return (
            self.db.query(TicketReferencia)
            .filter(TicketReferencia.id == ref_id)
            .first()
        )

    # ------------------------------------------------------------------ #
    # ELIMINAR
    # ------------------------------------------------------------------ #
    def eliminar(self, ref_id: int, usuario_id: Optional[int] = None) -> bool:
        """Elimina una referencia por ID. Retorna True si se eliminó.

        Antes de eliminar, captura un snapshot para auditoría.
        """
        ref = self.obtener(ref_id)
        if not ref:
            return False

        # Snapshot para auditoría
        origen_codigo = None
        destino_codigo = None
        try:
            origen = (
                self.db.query(Ticket).filter(Ticket.id == ref.ticket_origen_id).first()
            )
            destino = (
                self.db.query(Ticket).filter(Ticket.id == ref.ticket_referenciado_id).first()
            )
            origen_codigo = origen.codigo if origen else None
            destino_codigo = destino.codigo if destino else None
        except Exception:  # noqa: BLE001
            pass

        valor_anterior = {
            "tipo": ref.tipo.value if hasattr(ref.tipo, "value") else str(ref.tipo),
            "ticket_referenciado_id": ref.ticket_referenciado_id,
            "ticket_referenciado_codigo": destino_codigo,
            "nota": ref.nota,
        }

        self.db.delete(ref)

        try:
            auditoria = Auditoria(
                ticket_id=ref.ticket_origen_id,
                usuario_id=usuario_id,
                accion="referencia_eliminada",
                valor_anterior=valor_anterior,
                valor_nuevo=None,
                comentario=(
                    f"Referencia eliminada ({valor_anterior['tipo']}) → "
                    f"ticket {destino_codigo or ref.ticket_referenciado_id}"
                ),
            )
            self.db.add(auditoria)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[referencias] No se pudo preparar auditoría de "
                "eliminación: %s", e,
            )

        try:
            self.db.commit()
        except Exception as e:  # noqa: BLE001
            self.db.rollback()
            logger.exception("[referencias] Error al eliminar ref %s: %s", ref_id, e)
            raise
        return True

    # ------------------------------------------------------------------ #
    # AUTOCOMPLETAR (para el selector de tickets en la UI)
    # ------------------------------------------------------------------ #
    def buscar_tickets_para_autocompletar(
        self,
        query: str,
        exclude_ticket_id: Optional[int] = None,
        limit: int = 15,
    ) -> List[dict]:
        """Busca tickets por código o título para el selector con
        autocompletar.

        Args:
            query:               texto a buscar (mínimo 1 char).
            exclude_ticket_id:   ticket actual (se excluye de los resultados).
            limit:               máximo de resultados (cap 50).

        Returns:
            Lista de ``dict`` con {id, codigo, titulo, estado_id, estado_nombre}.
        """
        q = (query or "").strip()
        limit = max(1, min(int(limit or 15), 50))
        if not q:
            return []

        like_q = f"%{q}%"
        qry = self.db.query(Ticket).filter(
            Ticket.archivado == False  # noqa: E712
        )
        # Búsqueda por código, título o hu_o_caso_prueba
        qry = qry.filter(
            or_(
                Ticket.codigo.ilike(like_q),
                Ticket.titulo.ilike(like_q),
                Ticket.hu_o_caso_prueba.ilike(like_q),
            )
        )
        if exclude_ticket_id:
            qry = qry.filter(Ticket.id != exclude_ticket_id)

        qry = qry.order_by(Ticket.codigo.asc()).limit(limit)

        from app.models.estado import Estado

        resultados = []
        for t in qry.all():
            estado_nombre = None
            if t.estado_id:
                est = self.db.query(Estado).filter(Estado.id == t.estado_id).first()
                if est:
                    estado_nombre = est.nombre
            resultados.append({
                "id": t.id,
                "codigo": t.codigo,
                "titulo": (t.titulo or "")[:120],
                "estado_id": t.estado_id,
                "estado_nombre": estado_nombre,
            })
        return resultados

    # ------------------------------------------------------------------ #
    # HELPERS estáticos
    # ------------------------------------------------------------------ #
    @staticmethod
    def tipos_validos() -> List[dict]:
        """Devuelve el catálogo de tipos válidos con su nombre legible,
        pensado para popular un <select> en la UI.
        """
        return [
            {"value": t.value, "nombre": TIPO_REFERENCIA_NOMBRES.get(t, t.value)}
            for t in TipoReferencia
        ]

    @staticmethod
    def tipo_inverso(tipo: str) -> Optional[str]:
        """Devuelve el ``value`` del tipo inverso (o None si no aplica)."""
        try:
            t_enum = TipoReferencia(tipo)
        except ValueError:
            return None
        inv = TIPO_INVERSO.get(t_enum)
        return inv.value if inv else None
