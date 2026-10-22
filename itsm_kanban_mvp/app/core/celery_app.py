"""Celery application factory.

Configuración base que apunta a Redis como broker y result backend.
Las tareas se registran en `app.tasks.*`.
"""
from __future__ import annotations
from celery import Celery
from celery.schedules import crontab

from .config import settings


celery_app = Celery(
    "itsm_kanban",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.kanban_tasks"],
)

# Configuración
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=60,
    task_time_limit=120,
    broker_connection_retry_on_startup=True,
)

# Beat schedule: recalcular SLAs cada 5 minutos y notificaciones cada hora.
celery_app.conf.beat_schedule = {
    "recalcular-slas-vencidos": {
        "task": "app.tasks.kanban_tasks.recalcular_slas_vencidos",
        "schedule": crontab(minute="*/5"),
    },
    "notificar-cambios-pendientes": {
        "task": "app.tasks.kanban_tasks.notificar_cambios_pendientes",
        "schedule": crontab(minute=0),
    },
}
