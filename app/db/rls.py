"""
Row Level Security (RLS) de PostgreSQL para el aislamiento por proyecto.

V2.009 deja la capa de RLS ESCRITA y PREPARADA, pero **NO ACTIVADA**:

* las politicas se crean con ``ENABLE ROW LEVEL SECURITY`` (sin ``FORCE``),
  de modo que un rol *owner* — como el de siempre — las ignora y el
  comportamiento de la aplicacion no cambia;
* solo se aplican si el flag ``RLS_HABILITADO`` esta a True, cosa que ocurre
  en la ventana **V3 (el corte)**, junto con la creacion del rol de aplicacion
  sin privilegios de owner;
* en V2.009 el flag esta a False y, por tanto, este modulo no llega a
  ejecutarse en produccion.

Como funciona
--------------
El filtro ORM (``app/db/session.py``) es la PRIMERA capa de defensa: filtra en
Python, en la consulta. RLS es la SEGUNDA capa: filtra en el motor, de modo
que ningun camino que se salte el ORM (SQL crudo, una consulta escrita a mano,
un ``text()``) pueda ver filas de otro proyecto.

La politica lee el GUC de sesion ``app.proyecto_id``, que el listener
``after_begin`` de ``app/db/session.py`` fija con ``set_config(..., true)``
(ambito de transaccion). Ese GUC es el unico canal: no hay ninguna tabla de
"usuario actual" que un atacante pueda manipular desde la aplicacion.

Como la politica es fail-closed (``current_setting`` devuelve NULL si el GUC
no esta fijado, y entonces solo pasan las filas con ``proyecto_id IS NULL``),
un camino que se salte el filtro ORM veria menos filas, nunca mas.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


#: Prefijo de los nombres de politica. Se usa una politica por tabla (no por
#: columna) porque RLS se aplica a la FILA entera.
PREFIJO_POLITICA = "pol_proyecto_"


def _politica(tabla: str) -> str:
    """Devuelve la clausula USING/WITH CHECK de la politica de una tabla."""
    return (
        "(proyecto_id IS NOT DISTINCT FROM "
        "NULLIF(current_setting('app.proyecto_id', true), '')::int)"
    )


def politicas_rls(tablas: List[str]) -> List[Tuple[str, str]]:
    """
    Devuelve la lista de sentencias ``DROP`` + ``CREATE POLICY`` de las tablas
    indicadas. Es idempotente: PostgreSQL no admite ``CREATE POLICY IF NOT
    EXISTS``, asi que se borra la politica previa (si existe) antes de
    recrearla. Borrar y recrear LA MISMA politica no altera los datos.
    """
    sentencias: List[Tuple[str, str]] = []
    for tabla in tablas:
        nombre = "%s%s" % (PREFIJO_POLITICA, tabla)
        clausula = _politica(tabla)
        sentencias.append((
            "drop_policy_%s" % tabla,
            'DROP POLICY IF EXISTS "%s" ON "%s";' % (nombre, tabla),
        ))
        sentencias.append((
            "create_policy_%s" % tabla,
            'CREATE POLICY "%s" ON "%s" '
            'FOR ALL TO PUBLIC '
            'USING %s WITH CHECK %s;' % (nombre, tabla, clausula, clausula),
        ))
    return sentencias


def aplicar_politicas_rls(
    eng: Engine, tablas: List[str], forzar: bool = False
) -> Dict[str, int]:
    """
    Aplica ``ENABLE ROW LEVEL SECURITY`` y las politicas de las tablas dadas.

    Parametros
    ----------
    eng
        Motor contra el que aplicar el DDL.
    tablas
        Nombres de las tablas con ``proyecto_id``.
    forzar
        Si es True, ademas de ``ENABLE ROW LEVEL SECURITY`` se aplica
        ``FORCE ROW LEVEL SECURITY``, de modo que las politicas SE APLICAN
        TAMBIEN al rol owner. En produccion NO se quiere (el rol de aplicacion
        debe ser un rol normal, sin privilegios de owner: es la razon por la
        que RLS es una capa de defensa real). Se usa ``True`` en el clon de
        validacion, donde el unico rol disponible es ``postgres`` (owner), para
        poder comprobar que las politicas filtran de verdad.

    Devuelve un dict con los contadores ``politicas``, ``habilitadas``,
    ``forzadas`` y ``errores``.
    """
    stats = {"politicas": 0, "habilitadas": 0, "forzadas": 0, "errores": 0}
    with eng.begin() as conn:
        for etiqueta, sql in politicas_rls(tablas):
            try:
                conn.execute(text(sql))
                if etiqueta.startswith("create_policy"):
                    stats["politicas"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errores"] += 1
                logger.warning("[rls] no se pudo crear la politica %s: %s", etiqueta, exc)

        for tabla in tablas:
            try:
                conn.execute(text(
                    'ALTER TABLE "%s" ENABLE ROW LEVEL SECURITY' % tabla
                ))
                stats["habilitadas"] += 1
                if forzar:
                    conn.execute(text(
                        'ALTER TABLE "%s" FORCE ROW LEVEL SECURITY' % tabla
                    ))
                    stats["forzadas"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errores"] += 1
                logger.warning("[rls] no se pudo habilitar RLS en %s: %s", tabla, exc)

    logger.info(
        "[rls] politicas=%d habilitadas=%d forzadas=%d errores=%d",
        stats["politicas"], stats["habilitadas"], stats["forzadas"], stats["errores"],
    )
    return stats


def deshabilitar_rls(eng: Engine, tablas: List[str]) -> Dict[str, int]:
    """
    Desactiva RLS en las tablas indicadas (``NO FORCE RLS`` + ``DISABLE``).

    Es la operacion de reversion: deja la base de datos exactamente como
    estaba antes de aplicar las politicas. No borra datos ni columnas.
    """
    stats = {"deshabilitadas": 0, "errores": 0}
    with eng.begin() as conn:
        for tabla in tablas:
            try:
                conn.execute(text(
                    'ALTER TABLE "%s" NO FORCE ROW LEVEL SECURITY' % tabla
                ))
                conn.execute(text(
                    'ALTER TABLE "%s" DISABLE ROW LEVEL SECURITY' % tabla
                ))
                stats["deshabilitadas"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errores"] += 1
                logger.warning("[rls] no se pudo desactivar RLS en %s: %s", tabla, exc)
    logger.info(
        "[rls] deshabilitadas=%d errores=%d", stats["deshabilitadas"], stats["errores"],
    )
    return stats
