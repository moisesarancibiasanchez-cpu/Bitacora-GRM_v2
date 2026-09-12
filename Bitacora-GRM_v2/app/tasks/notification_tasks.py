"""
Tareas asíncronas de Celery: notificaciones de cambio de estado y SLA.
"""
import logging
from datetime import datetime, timedelta

from app.core.celery_app import celery_app
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.notification_tasks.notificar_cambio_estado", bind=True, max_retries=3)
def notificar_cambio_estado(self, ticket_id: int, estado_origen: str, estado_destino: str) -> dict:
    """
    Notifica a los interesados (asignado, creador) que el ticket cambió de estado.
    En producción: enviaría email, push, o usaría un webhook.
    """
    db = SessionLocal()
    try:
        from app.models.ticket import Ticket
        from app.models.usuario import Usuario
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return {"ok": False, "error": "ticket_no_existe"}

        destinatarios = []
        if ticket.asignado:
            destinatarios.append(ticket.asignado.email)
        if ticket.creador and ticket.creador.email not in destinatarios:
            destinatarios.append(ticket.creador.email)

        # En producción: enviar email vía SMTP o webhook Slack/Teams
        logger.info(
            f"[NOTIFICACIÓN] Ticket {ticket.codigo} cambió de "
            f"'{estado_origen}' a '{estado_destino}'. Destinatarios: {destinatarios}"
        )
        return {
            "ok": True,
            "ticket_id": ticket_id,
            "estado_origen": estado_origen,
            "estado_destino": estado_destino,
            "destinatarios": destinatarios,
            "fecha": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.exception("Error notificando cambio de estado")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.tasks.notification_tasks.notificar_sla_proximo_vencer")
def notificar_sla_proximo_vencer() -> dict:
    """Notifica tickets cuyo SLA está por vencer (próximas 4h) o ya vencido."""
    from app.services.sla_service import SLAService
    db = SessionLocal()
    try:
        service = SLAService(db)
        proximos = service.tickets_proximos_vencer(horas=4)
        vencidos = service.tickets_vencidos()
        return {
            "ok": True,
            "proximos_vencer": len(proximos),
            "vencidos": len(vencidos),
            "fecha": datetime.utcnow().isoformat(),
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.notification_tasks.limpiar_notificaciones_antiguas")
def limpiar_notificaciones_antiguas(dias: int = 90) -> dict:
    """Limpieza diaria de notificaciones antiguas (placeholder)."""
    return {"ok": True, "dias": dias, "fecha": datetime.utcnow().isoformat()}
