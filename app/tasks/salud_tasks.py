"""
Latido de salud de Celery (beat y worker).

Problema que resuelve
---------------------
Verificar que el *worker* y el *beat* de Railway estan vivos exigia acceso a
la API de Railway (token de proyecto) o a los logs del despliegue. Ninguna
de las dos fuentes esta siempre disponible, y sin ellas "el servicio esta
arriba" era una suposicion, no una comprobacion.

Este modulo aporta la señal que faltaba:

  - El BEAT planifica ``registrar_latido`` cada minuto y el WORKER la
    ejecuta: la clave de Redis dice si la cadena beat -> worker completo
    la tarea programada. Si la clave no existe o esta vencida, esa cadena
    no esta funcionando.
  - El WORKER se comprueba por separado con ``celery.control.ping()``: el
    worker responde al ping, de modo que la lista de workers que contestan
    es la prueba directa de que hay uno consumiendo la cola.

Distinguir "el beat no planifica" de "el worker no ejecuta" se hace
cruzan las dos senales: si el ping responde pero no hay latido, el fallo
esta en la planificacion; si el ping no responde, el worker esta caido.

Todo es de SOLO LECTURA desde el punto de vista de la aplicacion: el
latido se escribe en su propia clave de Redis, separada de las colas del
broker (base 1) y del backend de resultados (base 2).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)

#: Clave de Redis donde se guarda la hora del ultimo latido del beat.
#: Vive en la base 0 (``REDIS_URL``), separada de las colas del broker
#: (base 1) y del backend de resultados (base 2).
CLAVE_LATIDO = "bitacora:salud:beat"

#: Segundos de vida de la clave. Si el beat muere, la clave expira y el
#: endpoint puede decir "sin latido" en vez de mostrar un dato viejo.
TTL_LATIDO = 300


@celery_app.task(name="app.tasks.salud_tasks.registrar_latido")
def registrar_latido() -> dict:
    """Escribe en Redis la hora actual. La planifica el beat cada minuto.

    Si Redis no responde, la tarea NO falla: registraria el error y el
    beat seguiria planificando. La ausencia del latido ya se detecta
    desde ``/salud-celery``, que es donde tiene que verse.
    """
    from app.core.config import settings

    ahora = datetime.now(timezone.utc).isoformat()
    cliente = None
    try:
        import redis

        cliente = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        cliente.set(CLAVE_LATIDO, ahora, ex=TTL_LATIDO)
        return {"ok": True, "latido": ahora}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[salud:latido] No se pudo escribir el latido: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except Exception:  # noqa: BLE001
                pass


def leer_latido() -> dict:
    """Lee el ultimo latido del beat desde Redis.

    Devuelve un dict con ``ok``, ``latido`` (ISO 8601), ``antiguedad_segundos``
    y ``detalle``. Nunca lanza: un fallo de Redis se reporta como detalle.
    """
    from app.core.config import settings

    ahora = datetime.now(timezone.utc)
    cliente = None
    try:
        import redis

        cliente = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        bruto = cliente.get(CLAVE_LATIDO)
        if not bruto:
            return {
                "ok": False,
                "latido": None,
                "antiguedad_segundos": None,
                "detalle": (
                    "sin latido: la cadena beat -> worker no completo la tarea "
                    "programada (el beat no planifico, el worker no la ejecuto "
                    "o no puede hablar con Redis)"
                ),
            }
        marca = datetime.fromisoformat(bruto.decode("utf-8"))
        antiguedad = (ahora - marca).total_seconds()
        return {
            "ok": antiguedad <= TTL_LATIDO,
            "latido": marca.isoformat(),
            "antiguedad_segundos": round(antiguedad, 1),
            "detalle": (
                "OK"
                if antiguedad <= TTL_LATIDO
                else f"el ultimo latido es de hace {antiguedad:.0f}s (vencido)"
            ),        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "latido": None,
            "antiguedad_segundos": None,
            "detalle": f"error al leer Redis: {exc}",
        }
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except Exception:  # noqa: BLE001
                pass
