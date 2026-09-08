"""
Tareas asíncronas de Celery: recálculo de SLA.
Se ejecutan en segundo plano liberando el hilo principal de FastAPI.
"""
import logging
from datetime import datetime

from app.core.celery_app import celery_app
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.sla_tasks.recalcular_sla_ticket", bind=True, max_retries=3)
def recalcular_sla_ticket(self, ticket_id: int) -> dict:
    """Recalcula el SLA de un ticket concreto."""
    from app.services.sla_service import SLAService
    db = SessionLocal()
    try:
        service = SLAService(db)
        resultado = service.recalcular_ticket(ticket_id)
        logger.info(f"SLA recalculado para ticket {ticket_id}: {resultado}")
        return resultado
    except Exception as exc:
        logger.exception("Error recalculando SLA")
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


@celery_app.task(name="app.tasks.sla_tasks.recalcular_sla_masivo")
def recalcular_sla_masivo() -> dict:
    """Recorre todos los tickets activos y recalcula su SLA."""
    from app.models.ticket import Ticket
    from app.services.sla_service import SLAService
    db = SessionLocal()
    try:
        tickets = (
            db.query(Ticket)
            .filter(Ticket.sla_cumplido == -1)
            .all()
        )
        service = SLAService(db)
        procesados = 0
        for t in tickets:
            service.recalcular_ticket(t.id)
            procesados += 1
        return {"ok": True, "procesados": procesados, "fecha": datetime.utcnow().isoformat()}
    finally:
        db.close()
