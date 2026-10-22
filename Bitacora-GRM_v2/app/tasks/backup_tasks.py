"""
Tareas Celery para el sistema de respaldos de Base de Datos.

- ``backup_database_diario``: tarea programada (Beat) que ejecuta el backup
  completo a la hora configurada (BACKUP_DAILY_HOUR:BACKUP_DAILY_MINUTE,
  por defecto 00:00).

- ``backup_database_manual``: tarea invocable bajo demanda desde el endpoint
  REST o desde la acción Butler ``backup_database``. Es síncrona en su
  semántica (devuelve dict con resultado) aunque se ejecuta en el worker.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.celery_app import celery_app
from app.services.backup_service import (
    BackupResult,
    BackupService,
    get_backup_service,
)


logger = logging.getLogger(__name__)


def _result_to_dict(result: BackupResult) -> Dict[str, Any]:
    """Serializa un BackupResult a un dict apto para Celery."""
    return result.to_dict()


@celery_app.task(
    name="app.tasks.backup_tasks.backup_database_diario",
    bind=True,
    max_retries=2,
    default_retry_delay=300,  # 5 minutos
    acks_late=True,
)
def backup_database_diario(self, note: str = "scheduled") -> Dict[str, Any]:
    """Tarea programada (Beat) — backup diario a la hora configurada.

    Args:
        note: nota corta que se persiste en la metadata del .gz.

    Returns:
        Dict con el resultado estructurado del backup.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        service = get_backup_service()
        result = service.run_backup(note=note or "scheduled")
        if not result.ok:
            logger.error(
                "[BACKUP-TASK] Fallo backup diario: %s",
                result.error or result.skipped_reason,
            )
            # Si fue skipped por lock concurrente, no reintentar
            if result.skipped_reason:
                return {
                    "ok": False,
                    "started_at": started_at,
                    "skipped_reason": result.skipped_reason,
                }
            # Si fue error real, reintentar
            raise self.retry(exc=Exception(result.error or "error_unknown"))

        # Tras un backup exitoso, ejecutar limpieza de retención
        try:
            cleanup = service.cleanup_old_backups()
        except Exception as e:
            logger.warning("[BACKUP-TASK] Limpieza falló (no crítico): %s", e)
            cleanup = {"error": str(e)}

        return {
            "ok": True,
            "started_at": started_at,
            "metadata": _result_to_dict(result).get("metadata"),
            "cleanup": cleanup,
        }
    except Exception as exc:
        logger.exception("[BACKUP-TASK] Error inesperado")
        # No reintentar indefinidamente
        raise self.retry(exc=exc, countdown=300, max_retries=2)


@celery_app.task(
    name="app.tasks.backup_tasks.backup_database_manual",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def backup_database_manual(self, note: str = "manual") -> Dict[str, Any]:
    """Tarea invocable manualmente (endpoint REST o acción Butler).

    Diseñada para devolver rápido: si el worker está sobrecargado,
    el caller puede usar ``apply_async`` o llamar directamente a
    :func:`run_backup_sync`.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        service = get_backup_service()
        result = service.run_backup(note=note or "manual")
        return {
            "ok": result.ok,
            "started_at": started_at,
            "metadata": _result_to_dict(result).get("metadata"),
            "error": result.error,
            "skipped_reason": result.skipped_reason,
        }
    except Exception as exc:
        logger.exception("[BACKUP-TASK] Error en backup manual")
        return {
            "ok": False,
            "started_at": started_at,
            "error": str(exc),
        }


@celery_app.task(
    name="app.tasks.backup_tasks.backup_cleanup_old",
)
def backup_cleanup_old(retention_days: Optional[int] = None) -> Dict[str, Any]:
    """Tarea auxiliar: purga backups antiguos según la política de retención."""
    service = get_backup_service()
    return service.cleanup_old_backups(retention_days)


# ============================================================
# Helper sincrónico (uso directo desde la API REST o Butler)
# ============================================================
def run_backup_sync(note: str = "manual") -> Dict[str, Any]:
    """Ejecuta el backup directamente en el proceso actual.

    Útil cuando el caller quiere el resultado inmediato (por ejemplo,
    una solicitud HTTP del usuario que dispara el backup desde la UI).
    Evita la latencia de encolar en Celery.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    service = get_backup_service()
    result = service.run_backup(note=note)
    payload = {
        "ok": result.ok,
        "started_at": started_at,
        "metadata": _result_to_dict(result).get("metadata"),
        "error": result.error,
        "skipped_reason": result.skipped_reason,
    }
    if result.ok:
        # Limpieza en el mismo hilo (no es costosa)
        try:
            payload["cleanup"] = service.cleanup_old_backups()
        except Exception as e:
            payload["cleanup_error"] = str(e)
    return payload
