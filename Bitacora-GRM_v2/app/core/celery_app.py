"""
Configuración de Celery.
- Broker: Redis (cola de tareas)
- Backend: Redis (resultados)
- Beat: tareas programadas (recalcular SLA cada N minutos)
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings


def make_celery() -> Celery:
    """Crea y configura la instancia de Celery."""
    celery_app = Celery(
        "bitacora_grm",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.tasks.sla_tasks",
            "app.tasks.notification_tasks",
            # === FEATURE 2 — Triggers deadline ===
            "app.tasks.deadline_tasks",
        ],
    )

    # Configuración base
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=300,
        task_soft_time_limit=240,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=1000,
    )

    # Tareas programadas (Beat schedule)
    celery_app.conf.beat_schedule = {
        # Cada 5 minutos: recalcular SLA de tickets activos
        "recalcular-sla-cada-5-min": {
            "task": "app.tasks.sla_tasks.recalcular_sla_masivo",
            "schedule": crontab(minute="*/5"),
        },
        # Cada 15 minutos: notificar tickets cerca de vencer SLA
        "notificar-sla-proximo": {
            "task": "app.tasks.notification_tasks.notificar_sla_proximo_vencer",
            "schedule": crontab(minute="*/15"),
        },
        # Diario: cerrar tickets resueltos sin actividad
        "limpiar-tickets-inactivos": {
            "task": "app.tasks.notification_tasks.limpiar_notificaciones_antiguas",
            "schedule": crontab(hour=2, minute=0),
        },
        # === FEATURE 2 — Triggers deadline estilo Bitrix24 ===
        # Cada hora: revisar "approaching" (4h antes de vencer)
        "deadline-approaching-horario": {
            "task": "app.tasks.deadline_tasks.revisar_deadlines_horario",
            "schedule": crontab(minute=0),
        },
        # Diario 8 AM: revisar los 4 triggers (today/missed/approaching/overdue)
        "deadline-triggers-diario": {
            "task": "app.tasks.deadline_tasks.revisar_deadlines_diario",
            "schedule": crontab(hour=8, minute=0),
        },
    }

    return celery_app


celery_app = make_celery()
