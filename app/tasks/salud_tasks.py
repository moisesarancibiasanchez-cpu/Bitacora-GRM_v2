"""
Latido de salud de Celery (beat y worker).

Problema que resuelve
---------------------
Verificar que el *worker* y el *beat* de Railway estan vivos exigia acceso a
la API de Railway (token de proyecto) o a los logs del despliegue. Ninguna
de las dos fuentes esta siempre disponible, y sin ellas "el servicio esta
arriba" era una suposicion, no una comprobacion.

Este modulo aporta la senal que faltaba:

  - El BEAT escribe un latido en Redis en cada tick, mediante
    ``app.core.salud_scheduler.SaludScheduler``. Es la senal principal:
    depende SOLO del beat, que es exactamente lo que se quiere comprobar.
  - El WORKER ejecuta ``registrar_latido`` (esta misma tarea) y escribe
    tambien el latido: es un respaldo y cubre el caso de que el beat se
    reinicie entre ticks.
  - El WORKER se comprueba por separado con ``celery.control.ping()``: el
    worker responde al ping, de modo que la lista de workers que
    contestan es la prueba directa de que hay uno consumiendo la cola.

Distinguir "el beat no planifica" de "el worker no ejecuta" se hace
cruzan las dos senales: si el ping responde pero no hay latido, el fallo
esta en la planificacion; si el ping no responde, el worker esta caido.

Este modulo NO duplica la clave ni el TTL: estan en ``app.core.salud``,
que es el unico sitio donde se definen.
"""
from __future__ import annotations

import logging

from app.core.celery_app import celery_app
from app.core.salud import CLAVE_LATIDO, TTL_LATIDO, escribir_latido
from app.core.salud import leer_latido as _leer_latido

logger = logging.getLogger(__name__)

__all__ = ["CLAVE_LATIDO", "TTL_LATIDO", "registrar_latido", "leer_latido"]


@celery_app.task(name="app.tasks.salud_tasks.registrar_latido")
def registrar_latido() -> dict:
    """Escribe en Redis la hora actual.

    Si Redis no responde, la tarea NO falla: registraria el error y el
    worker seguiria consumiendo. La ausencia del latido ya se detecta
    desde ``/salud-celery``, que es donde tiene que verse.
    """
    return escribir_latido()


def leer_latido() -> dict:
    """Lee el ultimo latido del beat desde Redis.

    Devuelve un dict con ``ok``, ``latido`` (ISO 8601), ``antiguedad_segundos``
    y ``detalle``. Nunca lanza: un fallo de Redis se reporta como detalle.
    """
    return _leer_latido()
