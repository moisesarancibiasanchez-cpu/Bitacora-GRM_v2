"""Latido de salud de Celery: constantes y acceso a Redis.

SSOT del latido. Lo usan tres piezas y por eso vive aqui y no duplicado:

  - ``app.core.salud_scheduler.SaludScheduler``: el BEAT escribe el
    latido en cada tick. Es la senal que se quiere comprobar ("el beat
    sigue planificando") y NO depende del worker.
  - ``app.tasks.salud_tasks.registrar_latido``: la tarea Celery que
    escribe el latido cuando la ejecuta el worker. Es la misma senal por
    el otro camino (worker -> Redis) y sirve de respaldo.
  - ``app.main.salud_celery``: lee el latido y lo expone.

Por que el beat lo escribe el mismo y no solo el worker: si el latido
dependiera solo del worker, no se podria distinguir "el beat no
planifica" de "el worker no ejecuta". Escribiendolo el beat, el ping
(dice si el worker vive) y el latido (dice si el beat vive) son dos
senales independientes.

TTL: 900 s. El ``maxinterval`` por defecto del beat es de 300 s, asi que
un TTL de 300 s expiraria justo en el borde entre dos ticks y produciria
falsos negativos.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

#: Clave de Redis donde se guarda la hora del ultimo latido.
#: Vive en la base 0 (``REDIS_URL``), separada de las colas del broker
#: (base 1) y del backend de resultados (base 2).
CLAVE_LATIDO = "bitacora:salud:beat"

#: Segundos de vida de la clave. Si el beat muere, la clave expira y el
#: endpoint puede decir "sin latido" en vez de mostrar un dato viejo.
TTL_LATIDO = 900


def _cliente():
    """Crea un cliente de Redis contra ``settings.REDIS_URL``."""
    import redis

    from app.core.config import settings

    return redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def escribir_latido() -> dict:
    """Escribe la hora actual en Redis. Devuelve ``{"ok": bool, ...}``.

    Nunca lanza: si Redis no responde, el proceso que llama (el beat o el
    worker) debe seguir vivo. La ausencia del latido se detecta desde
    ``/salud-celery``, que es donde tiene que verse.
    """
    ahora = datetime.now(timezone.utc).isoformat()
    cliente = None
    try:
        cliente = _cliente()
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

    Devuelve un dict con ``ok``, ``latido`` (ISO 8601),
    ``antiguedad_segundos`` y ``detalle``. Nunca lanza: un fallo de Redis
    se reporta como detalle.
    """
    ahora = datetime.now(timezone.utc)
    cliente = None
    try:
        cliente = _cliente()
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
            ),
        }
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
