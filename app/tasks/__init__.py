"""Tareas de Celery."""
from app.tasks.sla_tasks import recalcular_sla_ticket, recalcular_sla_masivo
from app.tasks.notification_tasks import (
    notificar_cambio_estado,
    notificar_sla_proximo_vencer,
    limpiar_notificaciones_antiguas,
)

__all__ = [
    "recalcular_sla_ticket", "recalcular_sla_masivo",
    "notificar_cambio_estado", "notificar_sla_proximo_vencer",
    "limpiar_notificaciones_antiguas",
]
