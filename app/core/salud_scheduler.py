"""Scheduler de Celery que escribe el latido de salud del BEAT.

Por que un scheduler propio
---------------------------
El latido tiene que responder a UNA pregunta: "el beat sigue
planificando?". Si lo escribiera solo el worker (ejecutando la tarea
``app.tasks.salud_tasks.registrar_latido``), la ausencia del latido no
diria si el fallo esta en la planificacion del beat o en la ejecucion
del worker.

Este scheduler escribe el latido en el propio ``tick()`` del beat: la
senal depende SOLO del beat. El worker sigue teniendo su propia tarea
(respaldo, y para el caso de que el beat se reinicie), pero la prueba
principal no depende de el.

Se activa desde ``start.sh`` (solo en el rol beat):

    celery -A app.core.celery_app:celery_app beat \\
        --scheduler="app.core.salud_scheduler:SaludScheduler"

Si la escritura del latido falla (Redis caido), NO se tumba el beat: se
registra el aviso y el beat sigue planificando. La ausencia del latido
se detecta desde ``/salud-celery``.
"""
from __future__ import annotations

import logging

from celery.beat import PersistentScheduler

from app.core.salud import escribir_latido

logger = logging.getLogger(__name__)


class SaludScheduler(PersistentScheduler):
    """``PersistentScheduler`` que ademas escribe el latido de salud."""

    def tick(self, *args, **kwargs):
        """Escribe el latido y luego hace el tick normal de Celery."""
        try:
            escribir_latido()
        except Exception as exc:  # noqa: BLE001
            # Nunca debe tumbar el scheduler: el beat es mas importante
            # que el latido.
            logger.warning("[salud:scheduler] el latido no se pudo escribir: %s", exc)
        return super().tick(*args, **kwargs)
