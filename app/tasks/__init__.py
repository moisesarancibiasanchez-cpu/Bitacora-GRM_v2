"""Tareas de Celery."""
from app.tasks.sla_tasks import recalcular_sla_ticket, recalcular_sla_masivo
from app.tasks.notification_tasks import (
    notificar_cambio_estado,
    notificar_sla_proximo_vencer,
    limpiar_notificaciones_antiguas,
)
# === FEATURE 2 — Triggers de Deadline ===
from app.tasks.deadline_tasks import (
    revisar_deadlines_diario, revisar_deadlines_horario,
)

__all__ = [
    "recalcular_sla_ticket", "recalcular_sla_masivo",
    "notificar_cambio_estado", "notificar_sla_proximo_vencer",
    "limpiar_notificaciones_antiguas",
    # FEATURE 2
    "revisar_deadlines_diario", "revisar_deadlines_horario",
]
