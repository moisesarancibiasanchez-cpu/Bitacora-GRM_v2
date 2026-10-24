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
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base

logger = logging.getLogger(__name__)


def _normalizar_texto(valor: str) -> str:
    """Normaliza un nombre para compararlo de forma tolerante.

    Convierte a minúsculas, elimina los acentos y colapsa los espacios
    sobrantes. Se usa para comparar nombres de estados en las migraciones
    de datos: el nombre canónico del estado es ``'Producción OK'`` (con
    tilde), pero la comparación SQL ``LOWER(nombre) = 'produccion ok'``
    (sin tilde) NUNCA coincidía en PostgreSQL ni en SQLite.

    Esa incoherencia provocaba dos fallos reales:

    * el pre-check de 4.6 no encontraba el estado ya existente, así que en
      cada arranque se insertaba una fila **duplicada** de 'Producción OK';
    * los ``INSERT`` de 4.7 no resolvían los ids de origen/destino, así que
      las 3 transiciones del flujo 'Producción OK' **nunca** se creaban.

    Normalizar en Python es portable: funciona igual en PostgreSQL y SQLite
    sin depender de funciones de un dialecto concreto.
    """
    if not valor:
        return ""
    descompuesto = unicodedata.normalize("NFD", str(valor))
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return " ".join(sin_acentos.lower().split())


def _estados_por_nombre(conn, nombre_normalizado: str) -> List[int]:
    """Ids de todos los estados cuyo nombre normalizado coincide.

    Puede devolver más de un id: si una versión anterior de la migración
    insertó filas duplicadas de 'Producción OK' (por el bug de acentos),
    todas deben quedar conectadas con sus transiciones.
    """
    filas = conn.execute(text("SELECT id, nombre FROM estados")).fetchall()
    return [fila[0] for fila in filas if _normalizar_texto(fila[1]) == nombre_normalizado]


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
        # Feature nueva: responsable de la columna (FK a usuarios)
        # Cuando un ticket cae en este estado, el responsable recibe
        # notificación in-app + email.
        "responsable_id": (
            "INTEGER REFERENCES usuarios(id) ON DELETE SET NULL",
            "INTEGER REFERENCES usuarios(id) ON DELETE SET NULL",
        ),
        # FEATURE — Reporte diario de entregas.
        # True marca el estado como terminal de entrega. Cuando un ticket
        # entra en este estado por primera vez, se registra para el
        # reporte diario enviado por correo al final del día.
        "es_entrega": (
            "BOOLEAN NOT NULL DEFAULT FALSE",
            "BOOLEAN NOT NULL DEFAULT 0",
        ),
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
        # Campos extendidos del módulo de Incidencias (LOVs)
        "modulo": "VARCHAR(80)",
        # Ambiente: reemplaza al campo "Categoría" del antiguo catálogo.
        # LOV cerrado: QA / PRODUCCION.
        "ambiente": "VARCHAR(40)",
        # Ítem: subsistema o canal afectado. LOV cerrado: 3 valores.
        "item": "VARCHAR(80)",
        "vista": "VARCHAR(200)",
        "hu_o_caso_prueba": "VARCHAR(200)",
        "nota_observacion": "TEXT",
        "resultado_pruebas": "VARCHAR(40)",
        # QA Tester responsable de ejecutar las pruebas del ticket.
        # Se almacena como texto libre ``"Nombre <email>"`` para soportar
        # el LOV cerrado de QA Testers del sistema.
        "qa_tester": "VARCHAR(160)",
    },
    "adjuntos": {
        # Respaldo binario persistente: Railway tiene filesystem efímero y los
        # archivos en ``/app/uploads`` se borran en cada redeploy. Esta columna
        # (BYTEA en PG, BLOB en SQLite) garantiza que la descarga siga
        # funcionando aunque el archivo físico haya desaparecido.
        "contenido": ("BYTEA", "BLOB"),
        # FEATURE — Adjuntos dentro de comentarios.
        # NULL → el archivo pertenece al ticket (pestaña "Adjuntos", legacy).
        # <id> → el archivo pertenece a ese comentario (pestaña "Comentarios").
        # ON DELETE CASCADE: al borrar el comentario se borra su archivo.
        # IMPORTANTE: ``ticket_id`` sigue siendo NOT NULL y se rellena con el
        # ticket del comentario, por eso la FK va solo sobre comentario_id.
        "comentario_id": (
            "INTEGER REFERENCES comentarios(id) ON DELETE CASCADE",
            "INTEGER REFERENCES comentarios(id) ON DELETE CASCADE",
        ),
    },
}


# Índices que deben existir (idempotentes: IF NOT EXISTS funciona en ambos)
INDEXES: List[Tuple[str, str]] = [
    ("ix_estados_tablero_id",  "CREATE INDEX IF NOT EXISTS ix_estados_tablero_id ON estados(tablero_id)"),
    ("ix_estados_archivado",   "CREATE INDEX IF NOT EXISTS ix_estados_archivado  ON estados(archivado)"),
    ("ix_estados_es_entrega",  "CREATE INDEX IF NOT EXISTS ix_estados_es_entrega ON estados(es_entrega)"),
    ("ix_tickets_tablero_id",  "CREATE INDEX IF NOT EXISTS ix_tickets_tablero_id ON tickets(tablero_id)"),
    ("ix_tickets_archivado",   "CREATE INDEX IF NOT EXISTS ix_tickets_archivado  ON tickets(archivado)"),
    ("ix_tickets_posicion",    "CREATE INDEX IF NOT EXISTS ix_tickets_posicion   ON tickets(posicion)"),
    ("ix_tickets_fecha_inicio","CREATE INDEX IF NOT EXISTS ix_tickets_fecha_inicio ON tickets(fecha_inicio)"),
    ("ix_tickets_fecha_completado", "CREATE INDEX IF NOT EXISTS ix_tickets_fecha_completado ON tickets(fecha_completado)"),
    # FEATURE 3 — Gantt: dependencias entre tickets
    ("ix_dep_pred",            "CREATE INDEX IF NOT EXISTS ix_dep_pred ON ticket_dependencias(predecesor_id)"),
    ("ix_dep_suc",             "CREATE INDEX IF NOT EXISTS ix_dep_suc  ON ticket_dependencias(sucesor_id)"),
    # FEATURE 4 — Etapas de proyecto (sub-bars en Gantt)
    ("ix_etapas_orden",        "CREATE INDEX IF NOT EXISTS ix_etapas_orden      ON etapas_proyecto(orden)"),
    ("ix_te_ticket",           "CREATE INDEX IF NOT EXISTS ix_te_ticket         ON ticket_etapas(ticket_id)"),
    ("ix_te_etapa",            "CREATE INDEX IF NOT EXISTS ix_te_etapa          ON ticket_etapas(etapa_id)"),
    ("ix_te_orden",            "CREATE INDEX IF NOT EXISTS ix_te_orden          ON ticket_etapas(orden)"),
    # QA Tester asignado al ticket
    ("ix_tickets_qa_tester",   "CREATE INDEX IF NOT EXISTS ix_tickets_qa_tester ON tickets(qa_tester)"),
    # FEATURE 5 — Referencias internas entre tickets (issue links)
    ("ix_ref_origen",          "CREATE INDEX IF NOT EXISTS ix_ticket_referencias_ticket_origen_id ON ticket_referencias(ticket_origen_id)"),
    ("ix_ref_destino",         "CREATE INDEX IF NOT EXISTS ix_ticket_referencias_ticket_referenciado_id ON ticket_referencias(ticket_referenciado_id)"),
    ("ix_ref_created_at",      "CREATE INDEX IF NOT EXISTS ix_ticket_referencias_created_at ON ticket_referencias(created_at)"),
    ("ix_ref_origen_tipo",     "CREATE INDEX IF NOT EXISTS ix_ref_origen_tipo ON ticket_referencias(ticket_origen_id, tipo)"),
    ("ix_ref_destino_tipo",    "CREATE INDEX IF NOT EXISTS ix_ref_destino_tipo ON ticket_referencias(ticket_referenciado_id, tipo)"),
    # FEATURE 6 — Adjuntos de comentarios (búsqueda por comentario dueño)
    ("ix_adjuntos_comentario", "CREATE INDEX IF NOT EXISTS ix_adjuntos_comentario_id ON adjuntos(comentario_id)"),
]

# Tablas que deben existir (si el modelo está presente, ``create_all``
# las crea automáticamente al ejecutar ``apply_migrations``). Este set
# sirve para verificar manualmente o para tooling externo.
TABLES_REQUIRED: List[str] = [
    "ticket_dependencias",
    "ticket_referencias",
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
    stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0,
             "tables_created": 0, "data_migrated": 0}

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

    # 4) Migraciones de datos (idempotentes): cambios de nomenclatura
    #    y de valores permitidos. Se ejecutan en una TRANSACCIÓN SEPARADA
    #    para que un fallo en los datos NO haga rollback de las columnas/
    #    índices recién creados (lo que dejaría la app sin columnas y
    #    provocaría 500 al usarlas).
    try:
        with eng.begin() as conn:
            stats["data_migrated"] = _apply_data_migrations(conn, eng)
    except Exception as e:
        logger.warning(
            "[migrations] data: transacción de datos falló, pero las columnas/índices siguen intactos: %s",
            e,
        )
        stats["errors"] += 1

    logger.info(
        "[migrations] Resultado: applied=%d skipped=%d indexes=%d errors=%d data_migrated=%d",
        stats["applied"], stats["skipped"], stats["indexes"], stats["errors"],
        stats["data_migrated"],
    )
    return stats


def _apply_data_migrations(conn, eng: Engine) -> int:
    """
    Migraciones de datos idempotentes. Se aplican en cada arranque.

    - Normaliza ``resultado_pruebas``: ``POSTERGADA A GARANTÍA`` → ``POSTERGADA``
      (mantiene el valor anterior visible en ``nota_observacion`` si era
      relevante; en realidad el valor se renombra directamente porque solo
      cambia la etiqueta visible, el significado es el mismo).
    - Renombra ``codigo`` de tickets existentes al nuevo formato
      ``INC-NNN``: extrae el último segmento numérico de los codigos
      ``GRM-INC-YYYY-NNNNNN`` y lo reescribe.
    - Soft-delete de etiquetas prohibidas: ``Contabilidad``, ``software``,
      ``Ventas``, ``RRHH`` → ``activo = 0``. Esto las oculta de la UI sin
      perderlas en los tickets que ya las tengan asignadas.

    Cada paso está envuelto en su propio SAVEPOINT (``begin_nested()``)
    para que un fallo puntual no impida que los otros pasos se ejecuten.
    Ante un error, SQLAlchemy hace rollback únicamente al SAVEPOINT y la
    transacción exterior sigue vigente. Los errores se registran en el log
    y el método continúa.
    """
    total = 0
    is_pg = eng.dialect.name == "postgresql"
    ts_now = datetime.now(timezone.utc)

    # 4.1) Renombrar POSTERGADA A GARANTÍA → POSTERGADA
    try:
        with conn.begin_nested():
            # En PostgreSQL el UPDATE retorna el número de filas afectadas;
            # en SQLite depende del rowcount del cursor.
            res = conn.execute(text(
                "UPDATE tickets SET resultado_pruebas = 'POSTERGADA' "
                "WHERE resultado_pruebas = 'POSTERGADA A GARANTÍA'"
            ))
            n = res.rowcount if hasattr(res, "rowcount") else 0
            if n:
                logger.info("[migrations] data: %d tickets 'POSTERGADA A GARANTÍA' → 'POSTERGADA'", n)
                total += n
    except Exception as e:
        logger.warning(
            "[migrations] data: normalizar resultado_pruebas falló (aislado): %s", e
        )

    # 4.2) Renombrar codigos existentes GRM-INC-YYYY-NNNNNN → INC-NNN
    #      Solo afecta a los codigos que aún tengan el prefijo antiguo.
    #      El NNN se extrae del último segmento numérico (sin padding).
    try:
        with conn.begin_nested():
            if is_pg:
                # PostgreSQL: SUBSTRING con regex + CAST a int para limpiar ceros
                res = conn.execute(text(
                    "UPDATE tickets "
                    "SET codigo = 'INC-' || CAST(CAST(SUBSTRING(codigo FROM '([0-9]+)$') AS INTEGER) AS TEXT) "
                    "WHERE codigo ~ '^GRM-INC-[0-9]{4}-[0-9]+$'"
                ))
            else:
                # SQLite: emular con SUBSTR y CAST
                res = conn.execute(text(
                    "UPDATE tickets "
                    "SET codigo = 'INC-' || CAST(CAST(SUBSTR(codigo, -6) AS INTEGER) AS TEXT) "
                    "WHERE codigo LIKE 'GRM-INC-____-______'"
                ))
            n = res.rowcount if hasattr(res, "rowcount") else 0
            if n:
                logger.info("[migrations] data: %d tickets renombrados al formato INC-NNN", n)
                total += n
    except Exception as e:
        # No es fatal: si el regex no es soportado por esta versión de PG,
        # el código simplemente no se renombra. La app sigue funcionando.
        logger.warning(
            "[migrations] data: renombrar codigos falló (aislado, no fatal): %s", e
        )

    # 4.3) Soft-delete de etiquetas prohibidas.
    #      Compara en minúsculas para tolerar variantes de mayúsculas.
    try:
        with conn.begin_nested():
            # ``etiquetas.activo`` es BOOLEAN en PostgreSQL
            # (``app/models/etiqueta.py``: ``Column(Boolean)``). Con un
            # booleano, PostgreSQL rechaza tanto la comparación con un
            # entero (``operator does not exist: boolean <> integer``) como
            # la asignación de un entero
            # (``column "activo" is of type boolean but expression is of
            # type integer``). Por eso el literal cambia según el dialecto:
            # en PG se usa ``FALSE``/``IS TRUE``; en SQLite la columna se
            # almacena como entero y se conserva ``0``/``<> 0``.
            if is_pg:
                activo_set = "FALSE"
                activo_condition = "AND activo IS TRUE"
            else:
                activo_set = "0"
                activo_condition = "AND activo <> 0"
            res = conn.execute(text(
                f"UPDATE etiquetas SET activo = {activo_set} "
                "WHERE LOWER(TRIM(nombre)) IN ('contabilidad', 'software', 'ventas', 'rrhh') "
                f"{activo_condition}"
            ))
            n = res.rowcount if hasattr(res, "rowcount") else 0
            if n:
                logger.info("[migrations] data: %d etiquetas soft-deleted (Contabilidad, software, Ventas, RRHH)", n)
                total += n
    except Exception as e:
        logger.warning(
            "[migrations] data: ocultar etiquetas prohibidas falló (aislado, no fatal): %s", e
        )

    # 4.4) Relajar la restricción NOT NULL de ``auditorias.ticket_id``.
    #      La tabla registra eventos tanto de tickets como de
    #      usuarios/seguridad (envío de credenciales, login, edición de
    #      perfil). Cuando el evento NO está asociado a un ticket,
    #      ``ticket_id`` debe poder quedar en NULL.
    #      Esta migración es idempotente: si la columna ya acepta NULL,
    #      ``DROP NOT NULL`` no hace nada.
    try:
        with conn.begin_nested():
            if is_pg:
                # PostgreSQL: ``DROP NOT NULL`` es idempotente (si la columna
                # ya es nullable, ALTER TABLE la deja igual sin error).
                conn.execute(text(
                    "ALTER TABLE auditorias ALTER COLUMN ticket_id DROP NOT NULL"
                ))
                logger.info("[migrations] data: auditorias.ticket_id ahora permite NULL")
                total += 1
            else:
                # SQLite no soporta ALTER COLUMN. Se hace un check de pragma
                # para detectar si la columna ya es nullable; si no lo es,
                # se omite (es una BD de tests, no de producción).
                res = conn.execute(text("PRAGMA table_info(auditorias)"))
                cols = res.fetchall() if hasattr(res, "fetchall") else []
                for col in cols:
                    # PRAGMA table_info: (cid, name, type, notnull, dflt, pk)
                    if len(col) >= 4 and col[1] == "ticket_id" and col[3] == 1:
                        logger.warning(
                            "[migrations] data: SQLite: auditorias.ticket_id sigue siendo NOT NULL. "
                            "No se modifica (requeriría recrear la tabla)."
                        )
                        break
                else:
                    logger.info("[migrations] data: auditorias.ticket_id ya es nullable en SQLite")
    except Exception as e:
        logger.warning(
            "[migrations] data: relajar NOT NULL en auditorias.ticket_id falló (aislado): %s", e
        )

    # 4.5) Extender el enum nativo de PostgreSQL usado por la columna
    #      ``tickets.tipo`` con el valor ``RESULTADO_PRUEBAS`` que se
    #      añadió al enum de Python ``TipoIncidencia``. Sin esto, el
    #      INSERT/SELECT desde SQLAlchemy lanzaría
    #      ``InvalidTextRepresentation: invalid input value for enum
    #      <tipo>: "RESULTADO_PRUEBAS"`` aunque Python acepte el valor,
    #      y el endpoint ``/tickets/crear`` devolvería un 500 al guardar
    #      un ticket de tipo Resultado Pruebas.
    #
    #      IMPORTANTE: el valor se añade en MAYÚSCULAS porque la
    #      columna ``Column(Enum(TipoIncidencia))`` del modelo
    #      SQLAlchemy NO declara ``values_callable``, lo que hace que
    #      SQLAlchemy serialice los miembros del enum usando su
    #      ``.name`` (MAYÚSCULAS: ``INCIDENCIA``, ``SOLICITUD``, etc.)
    #      y NO su ``.value`` (``incidencia``, ``solicitud``, etc.).
    #      Por consistencia con el resto de valores ya presentes en
    #      el enum ``tipoincidencia`` de PG (que también están en
    #      MAYÚSCULAS), el valor nuevo se añade en MAYÚSCULAS.
    #      El ``.value`` del miembro Python (``"resultado_pruebas"``)
    #      se sigue usando para construir el enum desde el string
    #      que llega del frontend (``TipoIncidencia(tipo)`` busca
    #      por value).
    #
    #      Notas críticas:
    #      - El nombre real del tipo en PG lo detectamos mirando la
    #        columna ``tickets.tipo`` (no el primer enum que aparece),
    #        porque SQLAlchemy usa el nombre de la clase Python en
    #        minúsculas (``tipoincidencia``) y puede haber otros enums
    #        en la BD (p.ej. ``prioridad``). El ``LIMIT 1`` de la versión
    #        anterior era propenso a tomar el enum equivocado.
    #      - La extensión usa una conexión AUTOCOMMIT propia. En PG < 12,
    #        ``ALTER TYPE ... ADD VALUE`` no puede ejecutarse dentro de
    #        un bloque transaccional; en AUTOCOMMIT cada DDL es su propia
    #        transacción y el valor queda usable inmediatamente.
    #      - El camino completo, incluido ``RENAME VALUE``, requiere
    #        PG ≥ 10. ``ADD VALUE IF NOT EXISTS`` requiere PG ≥ 12; en
    #        PG 10/11 se comprueba primero y se usa ``ADD VALUE`` simple.
    #      - PG distingue MAYÚSCULAS de minúsculas en los valores de
    #        un enum. Si una versión anterior de la migración añadió
    #        ``'resultado_pruebas'`` (minúsculas) y luego se renombró
    #        esta sección a MAYÚSCULAS, el enum puede tener AMBOS
    #        valores o solo el de minúsculas. Para hacer la migración
    #        robusta frente a cualquier estado previo, primero
    #        RENAME del valor minúsculas → MAYÚSCULAS (si existe) y
    #        luego ADD VALUE IF NOT EXISTS (idempotente).
    if is_pg:
        enum_name = None
        enum_conn = None
        try:
            enum_conn = eng.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            )

            # 1) Detectar el enum EXACTO usado por ``tickets.tipo``.
            res = enum_conn.execute(text(
                "SELECT t.typname "
                "FROM pg_type t "
                "JOIN pg_attribute a ON a.atttypid = t.oid "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = 'tickets' "
                "  AND a.attname = 'tipo' "
                "  AND t.typtype = 'e' "
                "  AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
            ))
            row = res.fetchone() if hasattr(res, "fetchone") else None
            enum_name = row[0] if row else None

            if not enum_name:
                logger.warning(
                    "[migrations] data: no se encontró el enum usado por tickets.tipo; "
                    "no se extendió con 'RESULTADO_PRUEBAS'. Si tu tipo PG tiene un "
                    "nombre distinto, ejecuta manualmente: "
                    "ALTER TYPE <nombre> ADD VALUE IF NOT EXISTS 'RESULTADO_PRUEBAS';"
                )
            else:
                server_version_num = int(
                    enum_conn.execute(text("SHOW server_version_num")).scalar()
                )

                # 2) Si la versión anterior de la migración añadió
                #    ``'resultado_pruebas'`` (minúsculas), renombrarlo
                #    a MAYÚSCULAS para que coincida con la serialización
                #    que hace SQLAlchemy del miembro del enum.
                res_min = enum_conn.execute(text(
                    "SELECT 1 FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = :n AND e.enumlabel = 'resultado_pruebas'"
                ), {"n": enum_name})
                exists_min = res_min.fetchone() is not None
                res_may = enum_conn.execute(text(
                    "SELECT 1 FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = :n AND e.enumlabel = 'RESULTADO_PRUEBAS'"
                ), {"n": enum_name})
                exists_may = res_may.fetchone() is not None

                if exists_min and not exists_may:
                    if server_version_num >= 100000:
                        enum_conn.execute(text(
                            f"ALTER TYPE {enum_name} "
                            f"RENAME VALUE 'resultado_pruebas' TO 'RESULTADO_PRUEBAS'"
                        ))
                        logger.info(
                            "[migrations] data: enum PG '%s' renombrado "
                            "'resultado_pruebas' → 'RESULTADO_PRUEBAS'",
                            enum_name,
                        )
                        exists_may = True
                    else:
                        logger.warning(
                            "[migrations] data: no se pudo renombrar el valor "
                            "minúscula del enum PG '%s': RENAME VALUE requiere PG ≥ 10",
                            enum_name,
                        )
                elif exists_min and exists_may:
                    # Ambos existen (estado degenerado de un re-deploy
                    # durante una migración a medias). PG no permite DROP
                    # VALUE; el valor minúscula queda inerte porque
                    # SQLAlchemy ya usa el de mayúsculas.
                    logger.warning(
                        "[migrations] data: enum PG '%s' tiene TANTO "
                        "'resultado_pruebas' COMO 'RESULTADO_PRUEBAS'. "
                        "Esto es inofensivo (el de minúsculas queda "
                        "huérfano) pero puedes limpiarlo manualmente con: "
                        "ALTER TYPE %s RENAME VALUE 'resultado_pruebas' "
                        "TO 'RESULTADO_PRUEBAS_OLD';",
                        enum_name, enum_name,
                    )

                # 3) Extender el enum en su propia unidad transaccional.
                #    IF NOT EXISTS evita errores al reiniciar en PG ≥ 12.
                if not exists_may:
                    if server_version_num >= 120000:
                        enum_conn.execute(text(
                            f"ALTER TYPE {enum_name} "
                            f"ADD VALUE IF NOT EXISTS 'RESULTADO_PRUEBAS'"
                        ))
                    else:
                        enum_conn.execute(text(
                            f"ALTER TYPE {enum_name} "
                            f"ADD VALUE 'RESULTADO_PRUEBAS'"
                        ))

                # 4) Verificar que el valor en MAYÚSCULAS quedó
                #    registrado tras el commit (defensivo).
                res = enum_conn.execute(text(
                    "SELECT 1 FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = :n AND e.enumlabel = 'RESULTADO_PRUEBAS'"
                ), {"n": enum_name})
                ok = res.fetchone() is not None
                if ok:
                    logger.info(
                        "[migrations] data: enum PG '%s' contiene "
                        "'RESULTADO_PRUEBAS' (verificado)",
                        enum_name,
                    )
                    total += 1
                else:
                    logger.warning(
                        "[migrations] data: ALTER TYPE '%s' no logró "
                        "asegurar el valor 'RESULTADO_PRUEBAS'. Revisa "
                        "manualmente el estado del enum.",
                        enum_name,
                    )
        except Exception as e:
            logger.warning(
                "[migrations] data: extender el enum '%s' usado por "
                "tickets.tipo con 'RESULTADO_PRUEBAS' falló (aislado): %s",
                enum_name, e,
            )
        finally:
            if enum_conn is not None:
                enum_conn.close()

    # 4.6) Asegurar que existe el estado "Producción OK".
    #      Idempotente: solo se inserta si no existe por nombre. Esto
    #      cubre BDs que ya tienen los 6 estados anteriores (los seeds
    #      iniciales habrían fallado al saltarse por la guarda
    #      ``db.query(Estado).count() > 0``).
    #      Importante: la tabla ``estados`` hereda ``TimestampMixin``,
    #      por lo que ``created_at`` y ``updated_at`` son NOT NULL.
    #      Usamos ``datetime.now(timezone.utc)`` explícito en SQL porque
    #      ni SQLite ni PG aplican los defaults de SQLAlchemy al INSERT
    #      raw.
    #      La búsqueda es case-INSENSITIVE para tolerar BDs que ya
    #      tengan una versión previa con nombre distinto
    #      (``'produccion ok'``, ``'PRODUCCION OK'``, etc.).
    try:
        with conn.begin_nested():
            # Pre-check: ¿ya existe el estado "Producción OK"?
            # La comparación se hace con el texto NORMALIZADO (minúsculas y
            # sin acentos) para que 'Producción OK', 'produccion ok' y
            # 'PRODUCCION OK' sean el mismo estado. Antes se comparaba con
            # SQL contra el literal sin tilde ('produccion ok'), que jamás
            # coincidía con el nombre insertado ('Producción OK'): el
            # pre-check fallaba siempre y esta migración insertaba una
            # fila duplicada en CADA arranque de la aplicación.
            ids_existentes = _estados_por_nombre(conn, "produccion ok")
            existe_prod = bool(ids_existentes)
            if existe_prod and len(ids_existentes) > 1:
                logger.warning(
                    "[migrations] data: hay %d estados con el nombre 'Producción OK' "
                    "(ids=%s). Se conservan todos y se les crean sus transiciones.",
                    len(ids_existentes), ids_existentes,
                )
            if not existe_prod:
                if is_pg:
                    res = conn.execute(text(
                        "INSERT INTO estados (nombre, descripcion, color, orden, "
                        "es_inicial, es_final, categoria, sla_horas, archivado, "
                        "limite_wip, created_at, updated_at) "
                        "SELECT 'Producción OK', "
                        "       'Corrección desplegada y verificada en ambiente productivo', "
                        "       '#0d9488', COALESCE((SELECT MAX(orden)+1 FROM estados), 7), "
                        "       FALSE, TRUE, 'produccion_ok', NULL, FALSE, NULL, "
                        "       :ts, :ts"
                    ), {"ts": ts_now})
                else:
                    res = conn.execute(text(
                        "INSERT INTO estados (nombre, descripcion, color, orden, "
                        "es_inicial, es_final, categoria, sla_horas, archivado, "
                        "limite_wip, created_at, updated_at) "
                        "SELECT 'Producción OK', "
                        "       'Corrección desplegada y verificada en ambiente productivo', "
                        "       '#0d9488', COALESCE((SELECT MAX(orden)+1 FROM estados), 7), "
                        "       0, 1, 'produccion_ok', NULL, 0, NULL, :ts, :ts"
                    ), {"ts": ts_now})
                n = res.rowcount if hasattr(res, "rowcount") else 0
                if n:
                    logger.info("[migrations] data: estado 'Producción OK' insertado (orden=%s)", n)
                    total += n
            else:
                logger.info(
                    "[migrations] data: estado 'Producción OK' ya existe "
                    "(comparación normalizada, sin acentos); no se inserta"
                )
    except Exception as e:
        logger.warning(
            "[migrations] data: insertar estado 'Producción OK' falló (aislado): %s", e,
        )

    # 4.7) Asegurar que existen las 3 transiciones del flujo Producción OK.
    #      Idempotente: solo se inserta si NO existe ya la combinación
    #      (origen, destino) — case-insensitive para tolerar BDs con
    #      estados nombrados distinto (``'produccion ok'`` vs
    #      ``'Producción OK'``).
    try:
        nuevas_transiciones = [
            # (origen_lower, destino_lower, rol_requerido, requiere_comentario, descripcion)
            (
                "cerrado", "produccion ok", "agente_senior", 1,
                "Confirmar deploy verificado en producción. Obligatorio documentar build/PR/ambiente.",
            ),
            (
                "produccion ok", "cerrado", "agente_senior", 1,
                "Rollback: el deploy en producción tuvo un incidente. Obligatorio documentar el motivo.",
            ),
            (
                "produccion ok", "en curso", "administrador", 1,
                "Reabrir ticket: el fix en producción presenta un bug que requiere trabajo.",
            ),
        ]
        for origen_lc, destino_lc, rol, req_comentario, desc in nuevas_transiciones:
            try:
                with conn.begin_nested():
                    # Los ids de origen y destino se resuelven con la
                    # comparación NORMALIZADA (ver ``_estados_por_nombre``).
                    # Antes se comparaba en SQL contra literales sin tilde
                    # ('produccion ok'), que nunca coincidían con el nombre
                    # real del estado ('Producción OK'): los sub-SELECT de
                    # los INSERT devolvían NULL y las 3 transiciones del
                    # flujo 'Producción OK' NO SE CREABAN NUNCA.
                    ids_origen = _estados_por_nombre(conn, origen_lc)
                    ids_destino = _estados_por_nombre(conn, destino_lc)
                    if not ids_origen or not ids_destino:
                        logger.warning(
                            "[migrations] data: transición '%s'→'%s' NO insertada: "
                            "estado origen=%s destino=%s no encontrado en 'estados'.",
                            origen_lc, destino_lc, ids_origen or "∅", ids_destino or "∅",
                        )
                        continue
                    # Se inserta para CADA combinación origen×destino: si una
                    # versión anterior de esta migración dejó filas
                    # duplicadas de 'Producción OK', todas quedan conectadas.
                    for id_origen in ids_origen:
                        for id_destino in ids_destino:
                            # Pre-check idempotente por combinación de ids.
                            existe = conn.execute(text(
                                "SELECT 1 FROM transiciones_estado "
                                "WHERE estado_origen_id = :origen_id "
                                "  AND estado_destino_id = :destino_id"
                            ), {"origen_id": id_origen, "destino_id": id_destino}).fetchone()
                            if existe:
                                continue
                            res = conn.execute(text(
                                "INSERT INTO transiciones_estado "
                                "(estado_origen_id, estado_destino_id, rol_requerido, "
                                " requiere_comentario, descripcion) "
                                "VALUES (:origen_id, :destino_id, :rol, :req, :desc)"
                            ), {
                                "origen_id": id_origen, "destino_id": id_destino,
                                "rol": rol, "req": req_comentario, "desc": desc,
                            })
                            n = res.rowcount if hasattr(res, "rowcount") else 0
                            if n:
                                logger.info(
                                    "[migrations] data: transición '%s' → '%s' insertada "
                                    "(origen_id=%s destino_id=%s rol=%s)",
                                    origen_lc, destino_lc, id_origen, id_destino, rol,
                                )
                                total += n
            except Exception as e_inner:
                logger.warning(
                    "[migrations] data: insertar transición '%s'→'%s' falló "
                    "(aislado): %s",
                    origen_lc, destino_lc, e_inner,
                )
    except Exception as e:
        logger.warning(
            "[migrations] data: error general insertando transiciones de Producción OK: %s",
            e,
        )

    # 4.8) Asegurar que existen las 10 etapas del catálogo UAT.
    #      Idempotente: solo inserta las que faltan (por código). El
    #      catálogo se usa para renderizar las sub-bars del Gantt.
    #      Los códigos son slugs en MAYÚSCULAS que se referencian desde
    #      TicketEtapa y nunca se borran (soft-delete via `activo=0`).
    #
    #      ``ts_now`` se define al inicio de esta función y se reutiliza
    #      en los bloques 4.6 y 4.8 para compartir el mismo instante UTC.
    try:
        etapas_seed = [
            # (codigo,                 nombre,                                          orden, color)
            ("ESFUERZO",   "Medición de Esfuerzo",                1,  "#3b82f6"),
            ("ANALISIS",   "Análisis, Revisión y Aprobación",     2,  "#8b5cf6"),
            ("DESARROLLO", "Desarrollo",                          3,  "#06b6d4"),
            ("PRUEBAS_INT","Pruebas Internas",                    4,  "#10b981"),
            ("ENTREGA_QA", "Entrega y despliegue en QA",          5,  "#f59e0b"),
            ("INDUCCION",  "Inducción de HU",                     6,  "#ec4899"),
            ("PRUEBAS_C1", "Ejecución de pruebas ciclo 1",        7,  "#ef4444"),
            ("REV_UAT",    "Reuniones de Revisión UAT",           8,  "#a855f7"),
            ("CORRECC",    "Correcciones y despliegue",           9,  "#0ea5e9"),
            ("PRUEBAS_C2", "Ejecución de pruebas ciclo 2",        10, "#22c55e"),
        ]
        if is_pg:
            for codigo, nombre, orden, color in etapas_seed:
                try:
                    with conn.begin_nested():
                        # Comprobar existencia por código (case-sensitive)
                        existe = conn.execute(text(
                            "SELECT 1 FROM etapas_proyecto WHERE codigo = :c LIMIT 1"
                        ), {"c": codigo}).fetchone()
                        if existe:
                            continue
                        conn.execute(text(
                            "INSERT INTO etapas_proyecto "
                            "(codigo, nombre, orden, color, activo, "
                            " created_at, updated_at) "
                            "VALUES (:codigo, :nombre, :orden, :color, 1, :ts, :ts)"
                        ), {"codigo": codigo, "nombre": nombre,
                            "orden": orden, "color": color, "ts": ts_now})
                        logger.info(
                            "[migrations] data: etapa '%s' insertada (orden=%d)",
                            codigo, orden,
                        )
                        total += 1
                except Exception as e_inner:
                    logger.warning(
                        "[migrations] data: insertar etapa '%s' falló (aislado): %s",
                        codigo, e_inner,
                    )
        else:
            # SQLite: misma lógica pero con lazo separado para aislar errores
            for codigo, nombre, orden, color in etapas_seed:
                try:
                    with conn.begin_nested():
                        existe = conn.execute(text(
                            "SELECT 1 FROM etapas_proyecto WHERE codigo = :c LIMIT 1"
                        ), {"c": codigo}).fetchone()
                        if existe:
                            continue
                        conn.execute(text(
                            "INSERT INTO etapas_proyecto "
                            "(codigo, nombre, orden, color, activo, "
                            " created_at, updated_at) "
                            "VALUES (:codigo, :nombre, :orden, :color, 1, :ts, :ts)"
                        ), {"codigo": codigo, "nombre": nombre,
                            "orden": orden, "color": color, "ts": ts_now})
                        logger.info(
                            "[migrations] data: etapa '%s' insertada (orden=%d, SQLite)",
                            codigo, orden,
                        )
                        total += 1
                except Exception as e_inner:
                    logger.warning(
                        "[migrations] data: insertar etapa '%s' (SQLite) falló "
                        "(aislado): %s",
                        codigo, e_inner,
                    )
    except Exception as e:
        logger.warning(
            "[migrations] data: error general insertando etapas del proyecto: %s", e,
        )

    # 4.9) Reporte diario de entregas: marcar como ``es_entrega=True``
    #      los estados terminales reconocidos por convención. La
    #      comparación es case-insensitive y diacritic-insensitive
    #      (toleramos "ENTREGADO", "Entregado", "entregado", etc.).
    #      El admin puede luego agregar más estados desde la UI de
    #      configuración del reporte diario.
    try:
        with conn.begin_nested():
            if is_pg:
                res = conn.execute(text(
                    "UPDATE estados SET es_entrega = TRUE "
                    "WHERE LOWER(TRANSLATE(TRIM(nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) "
                    "IN ('entregado','entregada','resuelto','resuelta',"
                    "'cerrado','cerrada','completado','completada',"
                    "'finalizado','finalizada','produccion ok','deploy ok') "
                    "AND es_entrega = FALSE"
                ))
            else:
                res = conn.execute(text(
                    "UPDATE estados SET es_entrega = 1 "
                    "WHERE LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(TRIM(nombre),"
                    "'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u')) "
                    "IN ('entregado','entregada','resuelto','resuelta',"
                    "'cerrado','cerrada','completado','completada',"
                    "'finalizado','finalizada','produccion ok','deploy ok') "
                    "AND es_entrega = 0"
                ))
            n = res.rowcount if hasattr(res, "rowcount") else 0
            if n:
                logger.info(
                    "[migrations] data: %d estados marcados como es_entrega=True",
                    n,
                )
                total += n
    except Exception as e:
        logger.warning(
            "[migrations] data: marcar estados es_entrega falló (aislado): %s", e,
        )

    return total


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
