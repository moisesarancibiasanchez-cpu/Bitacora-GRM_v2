"""
FEATURE 2 — Tareas Celery para los 4 triggers de Deadline.

Este módulo expone 2 tareas:

    * ``revisar_deadlines_diario()``  → corre UNA vez al día (8 AM).
      Ejecuta los 4 triggers (today, missed, approaching, overdue).

    * ``revisar_deadlines_horario()`` → corre CADA hora.
      Ejecuta SOLO el trigger ``approaching`` (4h) para captar
      tickets que entran/salen de la ventana de las próximas 4h.

Conexión con Celery Beat (definida en ``app/core/celery_app.py``):

    beat_schedule={
        ...
        "revisar-deadlines-diario": {
            "task": "app.tasks.deadline_tasks.revisar_deadlines_diario",
            "schedule": crontab(hour=8, minute=0),
        },
        "revisar-deadlines-horario": {
            "task": "app.tasks.deadline_tasks.revisar_deadlines_horario",
            "schedule": crontab(minute=0),   # top of each hour
        },
    }

Por qué dos tareas y no una sola horaria que ejecute los 4:
    - ``today`` y ``missed`` y ``overdue`` no cambian mucho entre horas:
      el volumen de tickets que cumplen la condición solo crece en
      saltos discretos (cuando vence un nuevo ticket). Revisarlos
      cada hora generaría notificaciones duplicadas que la
      idempotencia (auditoría 24h) suprime, pero es desperdicio de
      queries.
    - ``approaching`` SÍ depende del tiempo actual: la ventana de "4h"
      se desliza continuamente, por lo que conviene chequearla a
      intervalos cortos.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict

from app.core.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _ejecutar_triggers_en_sesion() -> Dict[str, dict]:
    """Abre una sesión, ejecuta los triggers, retorna resumen.

    Esta función NO es una tarea Celery; es la lógica de negocio que
    reusan las dos tareas (``diario`` y ``horario``) para evitar
    duplicación.
    """
    from app.services.deadline_notifier import (
        ResultadoTrigger, ejecutar_todos_los_triggers,
        trigger_deadline_approaching,
    )
    db = SessionLocal()
    try:
        resultados = ejecutar_todos_los_triggers(db)
        return {
            trig: {
                "tickets_encontrados": r.tickets_encontrados,
                "notificaciones_creadas": r.notificaciones_creadas,
                "emails_enviados": r.emails_enviados,
                "errores_count": len(r.errores),
            }
            for trig, r in resultados.items()
        }
    finally:
        db.close()


# ============================================================================
# Tarea Celery 1: revisión DIARIA (los 4 triggers)
# ============================================================================
@celery_app.task(
    name="app.tasks.deadline_tasks.revisar_deadlines_diario",
    bind=True,
    max_retries=2,
    default_retry_delay=300,  # 5 min entre reintentos
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def revisar_deadlines_diario(self) -> dict:
    """Revisa los 4 triggers de deadline (today/missed/approaching/overdue).

    Pensado para correr 1× al día a las 8 AM (vía Celery Beat). Si
    Redis/Celery no está disponible, la tarea reintenta automáticamente
    hasta 2 veces con backoff.
    """
    try:
        logger.info("[deadline_task:diario] Iniciando revisión de 4 triggers")
        inicio = datetime.utcnow()
        resumen = _ejecutar_triggers_en_sesion()
        duracion_ms = (datetime.utcnow() - inicio).total_seconds() * 1000
        logger.info(
            "[deadline_task:diario] OK en %.0f ms — %s",
            duracion_ms, resumen,
        )
        return {"ok": True, "duracion_ms": duracion_ms, "resumen": resumen}
    except Exception as exc:
        logger.exception("[deadline_task:diario] Error: %s", exc)
        # Reintento automático (autoretry_for cubre Exception)
        raise self.retry(exc=exc)


# ============================================================================
# Tarea Celery 2: revisión HORARIA (solo ``approaching``)
# ============================================================================
@celery_app.task(
    name="app.tasks.deadline_tasks.revisar_deadlines_horario",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def revisar_deadlines_horario(self) -> dict:
    """Revisa SÓLO el trigger ``approaching`` (ventana 4h).

    Pensado para correr al inicio de cada hora. La ventana de 4h se
    desliza con el reloj, por lo que necesitamos chequeos frecuentes.
    La idempotencia (auditoría 24h) evita ráfagas si un ticket cumple
    la condición en 2 horas consecutivas (sólo recibe 1 notif/día).
    """
    try:
        from app.services.deadline_notifier import trigger_deadline_approaching
        db = SessionLocal()
        try:
            logger.info("[deadline_task:horario] Iniciando trigger 'approaching'")
            inicio = datetime.utcnow()
            r = trigger_deadline_approaching(db, ventana_horas=4)
            duracion_ms = (datetime.utcnow() - inicio).total_seconds() * 1000
            logger.info(
                "[deadline_task:horario] OK en %.0f ms — tickets=%d notifs=%d emails=%d",
                duracion_ms, r.tickets_encontrados,
                r.notificaciones_creadas, r.emails_enviados,
            )
            return {
                "ok": True,
                "duracion_ms": duracion_ms,
                "tickets_encontrados": r.tickets_encontrados,
                "notificaciones_creadas": r.notificaciones_creadas,
                "emails_enviados": r.emails_enviados,
            }
        finally:
            db.close()
    except Exception as exc:
        logger.exception("[deadline_task:horario] Error: %s", exc)
        raise self.retry(exc=exc)
