"""Tareas Celery: recálculo de SLAs y notificaciones."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
import logging

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.ticket import Ticket, PrioridadTicket
from app.models.sla import SLAPolitica
from app.models.auditoria import AuditoriaEvento, TipoEvento

logger = logging.getLogger(__name__)


def _calcular_fecha_vencimiento(prioridad: PrioridadTicket, minutos: int) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(minutes=minutos)


@celery_app.task(name="app.tasks.kanban_tasks.recalcular_sla_ticket")
def recalcular_sla_ticket(ticket_id: int) -> dict:
    """Recalcula el SLA de un ticket individual según su prioridad actual.

    - Lee la política default para la prioridad.
    - Si el ticket está en estado terminal, marca `sla_cumplido`.
    - Si está vencido, marca `sla_cumplido=False`.
    - Inserta un evento de auditoría SLA_CALCULADO.
    """
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        if not ticket:
            return {"ok": False, "error": "ticket_not_found", "ticket_id": ticket_id}

        politica = (
            db.query(SLAPolitica)
            .filter(
                SLAPolitica.prioridad == ticket.prioridad,
                SLAPolitica.es_default.is_(True),
                SLAPolitica.activo.is_(True),
            )
            .first()
        )
        if not politica:
            logger.warning("ticket_id=%s sin politica SLA para prioridad=%s", ticket_id, ticket.prioridad.value)
            return {"ok": False, "error": "no_sla_policy", "ticket_id": ticket_id}

        # Calcular / actualizar fecha de vencimiento SOLO si el ticket está abierto.
        if ticket.estado and ticket.estado.es_final:
            ticket.sla_cumplido = True
        else:
            if ticket.fecha_vencimiento_sla is None:
                ticket.fecha_vencimiento_sla = _calcular_fecha_vencimiento(ticket.prioridad, politica.minutos_resolucion)
            ahora = datetime.now(tz=timezone.utc)
            ticket.sla_cumplido = ahora <= ticket.fecha_vencimiento_sla

        # Auditoría obligatoria
        evento = AuditoriaEvento(
            ticket_id=ticket.id,
            tipo=TipoEvento.SLA_CALCULADO,
            actor_username="system",
            valor_anterior="",
            valor_nuevo=json.dumps({
                "fecha_vencimiento_sla": ticket.fecha_vencimiento_sla.isoformat() if ticket.fecha_vencimiento_sla else None,
                "sla_cumplido": ticket.sla_cumplido,
                "politica_id": politica.id,
                "minutos": politica.minutos_resolucion,
            }),
            comentario="Recálculo de SLA por tarea asíncrona Celery",
        )
        db.add(evento)
        db.commit()
        logger.info("SLA recalculado ticket_id=%s vence=%s cumplido=%s", ticket.id, ticket.fecha_vencimiento_sla, ticket.sla_cumplido)
        return {
            "ok": True,
            "ticket_id": ticket.id,
            "fecha_vencimiento_sla": ticket.fecha_vencimiento_sla.isoformat() if ticket.fecha_vencimiento_sla else None,
            "sla_cumplido": ticket.sla_cumplido,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Error recalculando SLA ticket_id=%s: %s", ticket_id, exc)
        return {"ok": False, "error": str(exc), "ticket_id": ticket_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.kanban_tasks.recalcular_slas_vencidos")
def recalcular_slas_vencidos() -> dict:
    """Job programado: recalcula SLA de todos los tickets abiertos cada 5 min."""
    db = SessionLocal()
    try:
        tickets_abiertos_ids = [
            t.id
            for t in db.query(Ticket).join(Ticket.estado).filter(Ticket.estado.has(es_final=False)).all()
        ]
        # Encolar recalcs individuales (no bloqueamos el beat).
        for tid in tickets_abiertos_ids:
            recalcular_sla_ticket.delay(tid)
        return {"ok": True, "encolados": len(tickets_abiertos_ids)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.kanban_tasks.notificar_cambio_estado")
def notificar_cambio_estado(ticket_id: int, estado_anterior: str, estado_nuevo: str) -> dict:
    """Notifica al creador/asignado sobre un cambio de estado del ticket.

    En el MVP solo registra el evento en la tabla auditoría; en producción
    se conectaría con SMTP, Slack, etc.
    """
    db = SessionLocal()
    try:
        evento = AuditoriaEvento(
            ticket_id=ticket_id,
            tipo=TipoEvento.NOTIFICACION_ENVIADA,
            actor_username="system",
            valor_anterior=estado_anterior,
            valor_nuevo=estado_nuevo,
            comentario="Notificación disparada por cambio de estado",
        )
        db.add(evento)
        db.commit()
        logger.info("Notificación registrada ticket_id=%s %s→%s", ticket_id, estado_anterior, estado_nuevo)
        return {"ok": True, "ticket_id": ticket_id}
    except Exception as exc:
        db.rollback()
        logger.exception("Error notificando cambio ticket_id=%s: %s", ticket_id, exc)
        return {"ok": False, "error": str(exc), "ticket_id": ticket_id}
    finally:
        db.close()


@celery_app.task(name="app.tasks.kanban_tasks.notificar_cambios_pendientes")
def notificar_cambios_pendientes() -> dict:
    """Job programado: placeholder para notificaciones batch (cron horario)."""
    logger.info("notificar_cambios_pendientes ejecutado (placeholder)")
    return {"ok": True, "ts": datetime.now(tz=timezone.utc).isoformat()}
