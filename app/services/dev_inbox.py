"""
Dev Inbox — Almacén de correos para entornos de desarrollo / pruebas.

Cuando el sistema no tiene SMTP configurado (o cuando se fuerza
explícitamente vía ``DEV_INBOX_ENABLED=true``), todos los correos que
la aplicación intenta enviar se guardan aquí para que un tester /
desarrollador / QA pueda revisarlos vía HTTP sin necesidad de un
servidor SMTP real ni de un dominio verificado en servicios como
Resend / SendGrid / Mailgun.

Características:
  - Multi-destinatario: soporta cualquier dirección (a diferencia de
    onboarding@resend.dev que solo envía al dueño de la API key).
  - Persistencia: usa Redis si está disponible (ideal para Railway,
    donde el filesystem es efímero). Si no, cae a un archivo JSONL
    en tmp/.
  - Capacidad limitada: por defecto conserva los últimos 200 correos.
  - Sin dependencias nuevas: solo redis-py (ya en requirements.txt).

No es un inbox de producción. En producción real, configura SMTP y
este módulo queda inactivo.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger(__name__)


# === Configuración ============================================================

# Máximo de correos que se conservan en el inbox (FIFO). Si llegan más,
# se eliminan los más antiguos para mantener el límite.
_MAX_RECORDS = int(os.getenv("DEV_INBOX_MAX", "200"))

# Si está definido en "true" / "1", el Dev Inbox se activa aunque haya
# SMTP configurado. Útil para hacer QA sin deshabilitar el SMTP real.
# Por defecto se activa SOLO cuando NO hay SMTP configurado.
_ENABLED_ENV = os.getenv("DEV_INBOX_ENABLED", "").lower() in ("1", "true", "yes")


def _smtp_configured() -> bool:
    """Replicamos la lógica del email_service para no acoplar."""
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def is_enabled() -> bool:
    """Devuelve True si el Dev Inbox debe capturar correos."""
    if _ENABLED_ENV:
        return True
    # Auto-activar cuando no hay SMTP configurado.
    return not _smtp_configured()


# === Modelo de un correo capturado ============================================

@dataclass
class InboxRecord:
    """Un correo capturado por el Dev Inbox."""
    id: str
    timestamp: float
    to: str
    cc: List[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    html_body: Optional[str] = None
    transport: str = "log"  # "log" (fallback) | "smtp-failed" (SMTP real cayó)
    sender: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# === Backend Redis (primario) ================================================

_REDIS_KEY = "bitacora:dev_inbox"


def _get_redis():
    """Devuelve un cliente Redis o None si no está disponible."""
    try:
        import redis  # type: ignore
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, decode_responses=True)
        # ping rápido para validar conectividad sin romper el flujo.
        client.ping()
        return client
    except Exception as exc:  # pragma: no cover
        logger.debug("[dev_inbox] Redis no disponible: %s", exc)
        return None


def _push_redis(client, record: InboxRecord) -> bool:
    try:
        # LPUSH inserta al inicio; LTRIM mantiene solo los últimos _MAX_RECORDS.
        client.lpush(_REDIS_KEY, json.dumps(record.to_dict(), ensure_ascii=False))
        client.ltrim(_REDIS_KEY, 0, _MAX_RECORDS - 1)
        return True
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo escribir en Redis: %s", exc)
        return False


def _list_redis(client) -> List[InboxRecord]:
    try:
        raw_items = client.lrange(_REDIS_KEY, 0, _MAX_RECORDS - 1)
        out: List[InboxRecord] = []
        for raw in raw_items:
            try:
                data = json.loads(raw)
                out.append(InboxRecord(**data))
            except Exception:
                continue
        return out
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo leer de Redis: %s", exc)
        return []


def _clear_redis(client) -> bool:
    try:
        client.delete(_REDIS_KEY)
        return True
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo limpiar Redis: %s", exc)
        return False


# === Backend filesystem (fallback) ===========================================

_LOG_DIR = Path("tmp")
_LOG_FILE = _LOG_DIR / "dev_inbox.jsonl"


def _ensure_log_dir() -> None:
    """Crea tmp/ tolerando que ya exista como archivo (mismo patrón
    defensivo que usa email_service)."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        # 'tmp' existe pero no es directorio: persistencia deshabilitada.
        pass
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo crear tmp/: %s", exc)


def _push_fs(record: InboxRecord) -> bool:
    _ensure_log_dir()
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo escribir en archivo: %s", exc)
        return False


def _list_fs() -> List[InboxRecord]:
    if not _LOG_FILE.exists():
        return []
    try:
        with _LOG_FILE.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        # Conservar solo los últimos _MAX_RECORDS (los más recientes).
        lines = lines[-_MAX_RECORDS:]
        out: List[InboxRecord] = []
        for line in lines:
            try:
                data = json.loads(line)
                out.append(InboxRecord(**data))
            except Exception:
                continue
        # Mantener el orden: más reciente primero.
        out.reverse()
        return out
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo leer el archivo: %s", exc)
        return []


def _clear_fs() -> bool:
    if not _LOG_FILE.exists():
        return True
    try:
        _LOG_FILE.unlink()
        return True
    except Exception as exc:
        logger.warning("[dev_inbox] No se pudo borrar el archivo: %s", exc)
        return False


# === API pública =============================================================

def add(
    *,
    to: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    cc: Optional[list] = None,
    transport: str = "log",
    sender: str = "",
) -> Optional[InboxRecord]:
    """Captura un correo en el Dev Inbox. Devuelve el record creado o None
    si el módulo está deshabilitado o no se pudo persistir."""
    if not is_enabled():
        return None

    record = InboxRecord(
        id=f"{int(time.time() * 1000)}-{hash(to + subject) & 0xffff:04x}",
        timestamp=time.time(),
        to=to,
        cc=list(cc) if cc else [],
        subject=subject,
        body=body,
        html_body=html_body,
        transport=transport,
        sender=sender or os.getenv("SMTP_FROM", ""),
    )

    client = _get_redis()
    if client is not None:
        if _push_redis(client, record):
            logger.info("[dev_inbox] OK (redis) -> %s | %s", to, subject)
            return record
        # Si Redis falló al escribir, intentamos filesystem como respaldo.
    if _push_fs(record):
        logger.info("[dev_inbox] OK (fs)    -> %s | %s", to, subject)
        return record
    return None


def list_recent(limit: Optional[int] = None) -> List[InboxRecord]:
    """Devuelve los correos capturados, más recientes primero."""
    client = _get_redis()
    if client is not None:
        items = _list_redis(client)
        if items or not _LOG_FILE.exists():
            return items[:limit] if limit else items
        # Si Redis está vacío pero hay archivo, leer del archivo.
    items = _list_fs()
    return items[:limit] if limit else items


def count() -> int:
    """Número de correos capturados actualmente."""
    client = _get_redis()
    if client is not None:
        try:
            return int(client.llen(_REDIS_KEY))
        except Exception:
            pass
    if not _LOG_FILE.exists():
        return 0
    try:
        with _LOG_FILE.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh if _.strip())
    except Exception:
        return 0


def clear() -> bool:
    """Borra todos los correos capturados."""
    ok = True
    client = _get_redis()
    if client is not None:
        ok = _clear_redis(client) and ok
    ok = _clear_fs() and ok
    return ok


def backend_info() -> dict:
    """Diagnóstico: qué backend está activo y por qué."""
    client = _get_redis()
    return {
        "enabled": is_enabled(),
        "explicitly_enabled": _ENABLED_ENV,
        "smtp_configured": _smtp_configured(),
        "backend": "redis" if client is not None else "filesystem",
        "redis_url": os.getenv("REDIS_URL", "") if client is not None else None,
        "max_records": _MAX_RECORDS,
        "stored": count(),
    }
