"""
Utilidades de zona horaria para Bitácora GRM.

Convención del proyecto:
  - **Base de datos**: se almacena SIEMPRE en UTC (naive, sin tzinfo) para
    mantener compatibilidad con SQLite/PostgreSQL sin romper migraciones.
  - **Capa de cálculo** (queries, filtros, deadlines SLA): se compara
    siempre contra ``now_utc()`` para evitar drift por TZ del servidor.
  - **Capa de presentación** (JSON para el front, strings en plantillas):
    se convierte con ``to_cl(dt)`` a la zona horaria operativa del
    equipo, ``America/Santiago`` (Chile continental). Desde 2019 Chile
    mantiene UTC-3 todo el año (DST derogado), por lo que el offset
    esperado es **siempre -03:00**.

Esta capa es la única autorizada a hablar de "hora local" en la app.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    # Python 3.9+: ``zoneinfo`` (stdlib). En Railway/Railpack viene
    # empaquetado en la imagen estándar.
    from zoneinfo import ZoneInfo
    CL_TZ: ZoneInfo = ZoneInfo("America/Santiago")
    _ZONEINFO_OK = True
except Exception:  # pragma: no cover - fallback degradado
    CL_TZ = timezone(-3, name="CLT-no-DST")  # fallback sin DST
    _ZONEINFO_OK = False


__all__ = [
    "CL_TZ",
    "now_utc",
    "now_cl",
    "to_cl",
    "fmt_cl",
    "fmt_cl_iso",
    "fmt_cl_for_js",
]


def now_utc() -> datetime:
    """Devuelve ``datetime`` naive en UTC, alineado con la convención
    de la BD (sin tzinfo). Equivalente a ``datetime.utcnow()`` pero
    sin el DeprecationWarning de Python 3.12+."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_cl() -> datetime:
    """Devuelve ``datetime`` TZ-aware en hora de Chile (CLT/CLST)."""
    return datetime.now(timezone.utc).astimezone(CL_TZ)


def to_cl(dt: Optional[datetime]) -> Optional[datetime]:
    """Convierte un datetime naive/aware a hora de Chile.

    - Si ``dt`` es *naive* se asume UTC (es lo que hay en la BD).
    - Si ``dt`` es *aware* se respeta su tzinfo y se convierte a CL.
    - Devuelve ``None`` si la entrada es ``None``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CL_TZ)


def fmt_cl(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Formatea ``dt`` en hora de Chile usando ``strftime``."""
    cl = to_cl(dt)
    if cl is None:
        return ""
    return cl.strftime(fmt)


def fmt_cl_iso(dt: Optional[datetime]) -> Optional[str]:
    """Devuelve ISO 8601 con offset real (ej. ``2026-10-05T20:47:14-03:00``).

    Útil para serializar en JSON que luego se renderiza con ``new Date(...)``
    en JS, porque el navegador puede entonces mostrarlo en hora local
    del usuario *sin* perder la zona de origen.
    """
    cl = to_cl(dt)
    if cl is None:
        return None
    return cl.isoformat()


def fmt_cl_for_js(dt: Optional[datetime]) -> str:
    """Conveniencia: ``fmt_cl_iso`` con fallback a string vacío."""
    return fmt_cl_iso(dt) or ""