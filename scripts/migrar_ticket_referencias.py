"""
Migración one-shot: crear tabla ``ticket_referencias``
=========================================================

FEATURE 5: Referencias Internas entre tickets.

Crea la tabla ``ticket_referencias`` con FK a ``tickets`` y ``usuarios``,
constraints de unicidad y anti auto-referencia, e índices compuestos para
las consultas bidireccionales frecuentes.

Uso
---
    cd /workspace
    .venv/bin/python -m scripts.migrar_ticket_referencias

Idempotente
-----------
Usa ``CREATE TABLE IF NOT EXISTS`` y ``CREATE INDEX IF NOT EXISTS``.
Re-ejecuciones no producen errores ni duplicados.

PostgreSQL (producción / Railway)
---------------------------------
Crea tipos ENUM, tabla con constraints CHECK, índices simples y
compuestos. Compatible con todas las versiones soportadas (>= 11).

SQLite (dev/test)
-----------------
SQLite no soporta ENUM nativo. Usamos VARCHAR(20) con CHECK constraint
para emular el dominio. SQLAlchemy ``Enum(native_enum=False)`` ya lo
genera así en ``Base.metadata.create_all``.
"""
import logging
import sys
from typing import Dict

from sqlalchemy import text

# Permitir imports relativos al proyecto cuando se ejecuta desde CLI
from app.db.session import SessionLocal
from app.db.base import Base
from app.models.ticket_referencia import TicketReferencia

logger = logging.getLogger(__name__)


def _detectar_dialect(db) -> str:
    """Devuelve el nombre del dialect (``postgresql``, ``sqlite`` ...)."""
    return db.bind.dialect.name if db.bind is not None else ""


# Tipos válidos para ``tipo``. Replicados aquí para CHECK constraint en
# SQLite (que no soporta ENUM nativo). En PostgreSQL se crea un TYPE.
TIPOS_VALIDOS = (
    "relacionado",
    "duplicado",
    "padre",
    "hijo",
    "bloquea",
    "bloqueado_por",
)


def _ddl_postgresql() -> str:
    """DDL específico para PostgreSQL."""
    tipos_enum_sql = "', '".join(TIPOS_VALIDOS)
    return f"""
    -- Tipo ENUM (idempotente vía DO block)
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tiporeferencia') THEN
            CREATE TYPE tiporeferencia AS ENUM ('{tipos_enum_sql}');
        END IF;
    END$$;

    -- Tabla principal
    CREATE TABLE IF NOT EXISTS ticket_referencias (
        id                       SERIAL PRIMARY KEY,
        ticket_origen_id         INTEGER NOT NULL
                                  REFERENCES tickets(id) ON DELETE CASCADE,
        ticket_referenciado_id   INTEGER NOT NULL
                                  REFERENCES tickets(id) ON DELETE CASCADE,
        tipo                     VARCHAR(20) NOT NULL DEFAULT 'relacionado',
        nota                     TEXT,
        creado_por_id            INTEGER
                                  REFERENCES usuarios(id) ON DELETE SET NULL,
        created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_ref_orig_dest_tipo
            UNIQUE (ticket_origen_id, ticket_referenciado_id, tipo),
        CONSTRAINT ck_ref_no_self_ref
            CHECK (ticket_origen_id <> ticket_referenciado_id)
    );

    -- Índices simples (FK + fecha)
    CREATE INDEX IF NOT EXISTS ix_ticket_referencias_ticket_origen_id
        ON ticket_referencias(ticket_origen_id);
    CREATE INDEX IF NOT EXISTS ix_ticket_referencias_ticket_referenciado_id
        ON ticket_referencias(ticket_referenciado_id);
    CREATE INDEX IF NOT EXISTS ix_ticket_referencias_created_at
        ON ticket_referencias(created_at);

    -- Índices compuestos (consulta bidireccional + filtro por tipo)
    CREATE INDEX IF NOT EXISTS ix_ref_origen_tipo
        ON ticket_referencias(ticket_origen_id, tipo);
    CREATE INDEX IF NOT EXISTS ix_ref_destino_tipo
        ON ticket_referencias(ticket_referenciado_id, tipo);
    """


def _ddl_sqlite() -> str:
    """DDL específico para SQLite (dev/tests)."""
    tipos_enum_sql = "', '".join(TIPOS_VALIDOS)
    return f"""
    CREATE TABLE IF NOT EXISTS ticket_referencias (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_origen_id         INTEGER NOT NULL
                                  REFERENCES tickets(id) ON DELETE CASCADE,
        ticket_referenciado_id   INTEGER NOT NULL
                                  REFERENCES tickets(id) ON DELETE CASCADE,
        tipo                     VARCHAR(20) NOT NULL DEFAULT 'relacionado'
                                  CHECK (tipo IN ('{tipos_enum_sql}')),
        nota                     TEXT,
        creado_por_id            INTEGER
                                  REFERENCES usuarios(id) ON DELETE SET NULL,
        created_at               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_ref_orig_dest_tipo
            UNIQUE (ticket_origen_id, ticket_referenciado_id, tipo),
        CONSTRAINT ck_ref_no_self_ref
            CHECK (ticket_origen_id <> ticket_referenciado_id)
    );

    CREATE INDEX IF NOT EXISTS ix_ticket_referencias_ticket_origen_id
        ON ticket_referencias(ticket_origen_id);
    CREATE INDEX IF NOT EXISTS ix_ticket_referencias_ticket_referenciado_id
        ON ticket_referencias(ticket_referenciado_id);
    CREATE INDEX IF NOT EXISTS ix_ticket_referencias_created_at
        ON ticket_referencias(created_at);

    CREATE INDEX IF NOT EXISTS ix_ref_origen_tipo
        ON ticket_referencias(ticket_origen_id, tipo);
    CREATE INDEX IF NOT EXISTS ix_ref_destino_tipo
        ON ticket_referencias(ticket_referenciado_id, tipo);
    """


def ejecutar_migracion() -> Dict:
    """Ejecuta la migración creando tabla ``ticket_referencias`` + índices.

    Returns
    -------
    dict con claves:
        - ``dialect``: dialecto detectado
        - ``applied``: bool — True si ejecutó el DDL
        - ``via_metadata``: bool — True si usó ``Base.metadata.create_all``
          (alternativa portable que SIEMPRE funciona)
        - ``error``: str | None
    """
    db = SessionLocal()
    resumen: Dict = {
        "dialect": None,
        "applied": False,
        "via_metadata": False,
        "error": None,
    }
    try:
        dialect = _detectar_dialect(db)
        resumen["dialect"] = dialect
        logger.info("[migracion-referencias] dialecto detectado: %s", dialect)

        # === Camino 1: DDL manual (PG / SQLite explícito) =================
        if dialect == "postgresql":
            sql = _ddl_postgresql()
        elif dialect == "sqlite":
            sql = _ddl_sqlite()
        else:
            logger.warning(
                "[migracion-referencias] Dialecto %s desconocido, "
                "intentando Base.metadata.create_all", dialect,
            )
            sql = None

        if sql is not None:
            # Ejecutar cada statement por separado (algunos clientes no
            # aceptan múltiples statements en un solo execute).
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                db.execute(text(stmt))
            db.commit()
            resumen["applied"] = True
            logger.info(
                "[migracion-referencias] DDL aplicado OK (dialect=%s)",
                dialect,
            )

        # === Camino 2 (respaldo): Base.metadata.create_all ===============
        # Garantiza que si el DDL manual falló (por permisos o por una
        # versión rara de PG sin DO $$), la tabla exista. Es idempotente
        # en cualquier motor.
        try:
            Base.metadata.create_all(bind=db.get_bind())
            resumen["via_metadata"] = True
            logger.info(
                "[migracion-referencias] Base.metadata.create_all OK "
                "(no-op si ya existe)",
            )
        except Exception as exc_meta:
            logger.warning(
                "[migracion-referencias] Base.metadata.create_all "
                "falló (no crítico): %s", exc_meta,
            )

        # === Verificar que la tabla existe =================================
        check_sql = text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'ticket_referencias' LIMIT 1"
            if dialect == "postgresql" else
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='ticket_referencias' LIMIT 1"
        )
        try:
            row = db.execute(check_sql).fetchone()
            if row is None:
                resumen["error"] = "tabla_no_creada"
                logger.error(
                    "[migracion-referencias] ✗ La tabla "
                    "ticket_referencias NO existe tras la migración",
                )
            else:
                logger.info(
                    "[migracion-referencias] ✓ tabla ticket_referencias "
                    "verificada en BD",
                )
        except Exception as exc_check:
            logger.warning(
                "[migracion-referencias] No se pudo verificar la "
                "existencia de la tabla: %s", exc_check,
            )

        return resumen

    except Exception as exc:
        db.rollback()
        logger.exception("[migracion-referencias] Error: %s", exc)
        resumen["error"] = str(exc)
        return resumen

    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print("=" * 70)
    print("  MIGRACIÓN: crear tabla ticket_referencias (FEATURE 5)")
    print("=" * 70)
    try:
        r = ejecutar_migracion()
        print(f"  dialect:        {r['dialect']}")
        print(f"  applied:        {r['applied']}")
        print(f"  via_metadata:   {r['via_metadata']}")
        if r["error"]:
            print(f"  error:          {r['error']}")
            sys.exit(1)
        print("=" * 70)
        print("  ✓ OK — tabla ticket_referencias lista")
        print("=" * 70)
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
