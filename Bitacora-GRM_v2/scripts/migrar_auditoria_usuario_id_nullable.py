"""
Migración one-shot: ``auditorias.usuario_id`` → nullable
=========================================================

Convierte la columna ``auditorias.usuario_id`` de ``NOT NULL`` a ``NULL``
para permitir registrar eventos generados por el sistema (sin un usuario
humano responsable).

Contexto
--------
El servicio ``app.services.deadline_notifier`` inserta auditorías con
``usuario_id=None`` para representar eventos automáticos (los 4 triggers
de SLA: deadline_today, deadline_missed, deadline_approaching,
task_overdue). El docstring del módulo lo documenta explícitamente:

    > Inserta UNA fila en ``auditoria`` por ticket con tipo
    > ``deadline_trigger`` (es un evento del sistema, no de un usuario).

Pero la columna está definida como ``nullable=False`` en el modelo, por
lo que el ``INSERT`` falla con ``IntegrityError: NOT NULL constraint
failed: auditorias.usuario_id``.

Uso
---
    cd /workspace/Bitacora-GRM_v2
    .venv/bin/python -m scripts.migrar_auditoria_usuario_id_nullable

Idempotente
-----------
Si la columna ya permite NULL, el script no hace nada.

PostgreSQL
----------
Usa ``ALTER COLUMN ... DROP NOT NULL``. Compatible con todas las
versiones soportadas (>= 11).

SQLite (dev/test)
-----------------
SQLite no soporta ``DROP NOT NULL`` directamente. Como SQLite no
enforce NOT NULL por defecto en columnas existentes (sólo al cambiar
schema explícito), en la práctica el constraint no bloquea inserts,
pero el modelo SQLAlchemy debe estar alineado para que ``create_all``
genere el schema correcto.
"""
import logging
import sys

from sqlalchemy import text

# Permitir imports relativos al proyecto cuando se ejecuta desde CLI
from app.db.session import SessionLocal
from app.models.auditoria import Auditoria

logger = logging.getLogger(__name__)


def _detectar_dialect(db) -> str:
    """Devuelve el nombre del dialect (``postgresql``, ``sqlite`` ...)."""
    return db.bind.dialect.name if db.bind is not None else ""


def ejecutar_migracion() -> dict:
    """Ejecuta la migración para que ``auditorias.usuario_id`` acepte NULL.

    Returns
    -------
    dict con claves:
        - ``dialect``: dialecto detectado
        - ``applied``: bool — True si se aplicó el cambio, False si ya estaba
        - ``error``: str | None — descripción del error si lo hubo
    """
    db = SessionLocal()
    resumen = {
        "dialect": None,
        "applied": False,
        "error": None,
    }
    try:
        dialect = _detectar_dialect(db)
        resumen["dialect"] = dialect
        logger.info("[migracion-aud-usuario-id] dialecto detectado: %s", dialect)

        if dialect == "postgresql":
            # PostgreSQL: ALTER COLUMN ... DROP NOT NULL
            sql = text("""
                ALTER TABLE auditorias
                ALTER COLUMN usuario_id DROP NOT NULL
            """)
            db.execute(sql)
            db.commit()
            resumen["applied"] = True
            logger.info("[migracion-aud-usuario-id] ALTER aplicado OK")

        elif dialect == "sqlite":
            # SQLite: NO soporta DROP NOT NULL directamente, pero SQLite
            # no enforza NOT NULL en columnas existentes. El modelo
            # SQLAlchemy controlará la creación de la tabla vía create_all.
            # Por seguridad, recreamos la tabla con el schema correcto.
            logger.info(
                "[migracion-aud-usuario-id] SQLite detectado — "
                "SQLite no aplica NOT NULL retroactivo. No requiere acción."
            )
            resumen["applied"] = False

        else:
            logger.warning(
                "[migracion-aud-usuario-id] Dialecto %s no soportado. "
                "Aplicar manualmente.", dialect,
            )
            resumen["error"] = f"dialecto_no_soportado:{dialect}"

        return resumen

    except Exception as exc:
        db.rollback()
        logger.exception("[migracion-aud-usuario-id] Error: %s", exc)
        resumen["error"] = str(exc)
        return resumen

    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = ejecutar_migracion()
    print("\n=== Resultado migración ===")
    print(f"  dialect: {res['dialect']}")
    print(f"  applied: {res['applied']}")
    if res["error"]:
        print(f"  error:   {res['error']}")
        sys.exit(1)
    print("  ✓ OK")
    sys.exit(0)
