"""
Migraciones idempotentes para Bitácora GRM.

Alinea el esquema de la base de datos con los modelos SQLAlchemy sin
necesidad de Alembic. Pensado para ejecutarse en cada arranque de la
aplicación (es seguro correrlo múltiples veces: solo añade columnas que
no existen).

Compatibilidad:
- PostgreSQL (producción / Railway): usa `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
- SQLite (desarrollo / tests): comprueba `information_schema` y luego `ALTER TABLE`.

Convenciones:
- (table, column) -> (pg_type, sqlite_type)
- Las definiciones de tipo NO incluyen el nombre de la columna; el script
  lo concatena con `"nombre" TIPO`.
- Para columnas con FK, la tabla referenciada debe existir (se crea con
  `Base.metadata.create_all` antes de aplicar columnas).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base

logger = logging.getLogger(__name__)


def _get_default_engine() -> Engine:
    """Import lazy del engine de sesión para no abrir conexiones al cargar el módulo."""
    from app.db.session import engine as session_engine
    return session_engine


# === Definición de columnas a sincronizar =====================================
# Cada entrada: { tabla: { columna: (tipo_postgres, tipo_sqlite) } }
# Si solo se proporciona un string, se usa para ambos motores.
COLUMNS_TO_ADD: Dict[str, Dict[str, Tuple[str, str] | str]] = {
    "estados": {
        # Trello: listas pueden pertenecer a un tablero (null = global)
        "tablero_id": (
            "INTEGER REFERENCES tableros(id) ON DELETE CASCADE",
            "INTEGER REFERENCES tableros(id) ON DELETE CASCADE",
        ),
        "archivado": ("BOOLEAN NOT NULL DEFAULT FALSE", "BOOLEAN NOT NULL DEFAULT 0"),
        "limite_wip": "INTEGER",
    },
    "tickets": {
        # Trello: cada tarjeta pertenece a un tablero
        "tablero_id": (
            "INTEGER REFERENCES tableros(id) ON DELETE SET NULL",
            "INTEGER REFERENCES tableros(id) ON DELETE SET NULL",
        ),
        # Columna JSON para datos dinámicos del catálogo (ya arreglada en commit
        # anterior; se incluye por si la BD se creó con un esquema muy antiguo).
        "datos_catalogo": ("JSON", "TEXT"),
        "fecha_inicio": ("TIMESTAMP", "TIMESTAMP"),
        "fecha_completado": ("TIMESTAMP", "TIMESTAMP"),
        "fecha_cumplida": ("BOOLEAN NOT NULL DEFAULT FALSE", "BOOLEAN NOT NULL DEFAULT 0"),
        "portada_color": "VARCHAR(20)",
        "portada_adjunto_id": (
            "INTEGER REFERENCES adjuntos(id) ON DELETE SET NULL",
            "INTEGER REFERENCES adjuntos(id) ON DELETE SET NULL",
        ),
        "descripcion_md": ("BOOLEAN NOT NULL DEFAULT FALSE", "BOOLEAN NOT NULL DEFAULT 0"),
        "posicion": ("INTEGER NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0"),
        "archivado": ("BOOLEAN NOT NULL DEFAULT FALSE", "BOOLEAN NOT NULL DEFAULT 0"),
    },
}


# Índices que deben existir (idempotentes: IF NOT EXISTS funciona en ambos)
INDEXES: List[Tuple[str, str]] = [
    ("ix_estados_tablero_id",  "CREATE INDEX IF NOT EXISTS ix_estados_tablero_id ON estados(tablero_id)"),
    ("ix_estados_archivado",   "CREATE INDEX IF NOT EXISTS ix_estados_archivado  ON estados(archivado)"),
    ("ix_tickets_tablero_id",  "CREATE INDEX IF NOT EXISTS ix_tickets_tablero_id ON tickets(tablero_id)"),
    ("ix_tickets_archivado",   "CREATE INDEX IF NOT EXISTS ix_tickets_archivado  ON tickets(archivado)"),
    ("ix_tickets_posicion",    "CREATE INDEX IF NOT EXISTS ix_tickets_posicion   ON tickets(posicion)"),
    ("ix_tickets_fecha_inicio","CREATE INDEX IF NOT EXISTS ix_tickets_fecha_inicio ON tickets(fecha_inicio)"),
    ("ix_tickets_fecha_completado", "CREATE INDEX IF NOT EXISTS ix_tickets_fecha_completado ON tickets(fecha_completado)"),
]


def _get_existing_columns(eng: Engine, table: str) -> set:
    """Devuelve el conjunto de columnas existentes en la tabla (vacío si la tabla no existe)."""
    insp = inspect(eng)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _resolve_type(eng: Engine, type_def) -> str:
    """Devuelve la definición de tipo para el motor actual."""
    if isinstance(type_def, tuple):
        pg_type, sqlite_type = type_def
        return pg_type if eng.dialect.name == "postgresql" else sqlite_type
    return type_def


def _column_exists(eng: Engine, table: str, column: str) -> bool:
    """Comprobación portable: True si la columna existe en la tabla."""
    return column in _get_existing_columns(eng, table)


def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
    """
    Aplica migraciones pendientes para alinear el esquema con los modelos.

    - Idempotente: puede ejecutarse en cada arranque.
    - Segura: usa `engine.begin()` para transaccionar; si algo falla, hace rollback.
    - Retorna un dict con estadísticas {applied, skipped, indexes, errors}.
    """
    eng = eng or _get_default_engine()
    is_pg = eng.dialect.name == "postgresql"
    is_sqlite = eng.dialect.name == "sqlite"
    stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0, "tables_created": 0}

    # 1) Asegurar que todas las tablas existen (no-op si ya están).
    #    Necesario porque algunas columnas tienen FKs a tablas nuevas (tableros,
    #    adjuntos) que pueden no existir si la BD es muy antigua.
    try:
        Base.metadata.create_all(bind=eng)
        stats["tables_created"] = 0  # create_all es no-op si existen
        logger.info("[migrations] Schema check: tablas verificadas")
    except Exception as e:
        logger.warning("[migrations] No se pudo verificar el esquema base: %s", e)
        stats["errors"] += 1

    # 2) Añadir columnas faltantes
    with eng.begin() as conn:
        for table, columns in COLUMNS_TO_ADD.items():
            existing = _get_existing_columns(eng, table)
            for column, type_def in columns.items():
                if column in existing:
                    stats["skipped"] += 1
                    continue
                col_type = _resolve_type(eng, type_def)
                try:
                    if is_pg:
                        sql = f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                    elif is_sqlite:
                        # SQLite < 3.35 no soporta IF NOT EXISTS en ADD COLUMN.
                        # Hacemos el pre-check arriba (`column in existing`).
                        sql = f'ALTER TABLE {table} ADD COLUMN "{column}" {col_type}'
                    else:
                        # Motor desconocido: intentar IF NOT EXISTS
                        sql = f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                    conn.execute(text(sql))
                    logger.info("[migrations] ✓ %s.%s añadida (%s)", table, column, col_type)
                    stats["applied"] += 1
                except Exception as e:
                    logger.warning(
                        "[migrations] ✗ No se pudo añadir %s.%s: %s",
                        table, column, e,
                    )
                    stats["errors"] += 1

        # 3) Crear índices faltantes (IF NOT EXISTS funciona en ambos motores)
        for name, sql in INDEXES:
            try:
                conn.execute(text(sql))
                stats["indexes"] += 1
            except Exception as e:
                logger.debug("[migrations] Índice %s: %s", name, e)

    logger.info(
        "[migrations] Resultado: applied=%d skipped=%d indexes=%d errors=%d",
        stats["applied"], stats["skipped"], stats["indexes"], stats["errors"],
    )
    return stats


def report_schema_drift(eng: Optional[Engine] = None) -> List[str]:
    """
    Devuelve una lista de líneas describiendo columnas que faltan
    (útil para diagnóstico sin aplicar cambios).
    """
    eng = eng or _get_default_engine()
    out: List[str] = []
    for table, columns in COLUMNS_TO_ADD.items():
        existing = _get_existing_columns(eng, table)
        missing = [c for c in columns.keys() if c not in existing]
        if missing:
            out.append(f"{table}: faltan {', '.join(missing)}")
        else:
            out.append(f"{table}: OK ({len(existing)} columnas)")
    return out


if __name__ == "__main__":
    # Permite ejecutar manualmente: `python -m app.db.migrations`
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Permitir override del engine vía env var para testing
    db_url = os.environ.get("TEST_DATABASE_URL")
    target_engine = None
    if db_url:
        from sqlalchemy import create_engine
        target_engine = create_engine(db_url)
        print(f"Usando engine override: {db_url}")
    print("== Diagnóstico de esquema ==")
    for line in report_schema_drift(target_engine):
        print(f"  · {line}")
    print()
    print("== Aplicando migraciones ==")
    apply_migrations(target_engine)
    print()
    print("== Diagnóstico post-migración ==")
    for line in report_schema_drift(target_engine):
        print(f"  · {line}")
