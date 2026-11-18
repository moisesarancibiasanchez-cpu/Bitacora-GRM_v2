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


# ============================================================================ #
# V2.009 — AISLAMIENTO POR PROYECTO (ventana aditiva)
# ============================================================================ #
# La columna ``proyecto_id`` se anade a las tablas de negocio para poder
# aislar los datos por proyecto (multi-tenancy) sin depender de la jerarquia
# Espacio -> Tablero -> Ticket, que no se aplicaba en las consultas de
# tickets.
#
# Es ADITIVO en el sentido estricto del lote:
#   * la columna es NULLABLE (el paso a NOT NULL es de la ventana V3, el corte);
#   * no se borra ni se renombra ninguna columna, indice o restriccion;
#   * el backfill solo RELLENA la columna nueva con el proyecto "Legacy" (id 1),
#     de modo que los datos existentes son los mismos de siempre;
#   * el filtro ORM y las politicas RLS quedan INERTES hasta que se active
#     ``AISLAMIENTO_PROYECTO_ACTIVO`` (ventana V3).
#
# Las tablas de asociacion (espacio_miembros, ticket_etiquetas,
# ticket_miembros) NO llevan ``proyecto_id``: son tablas puente y su
# aislamiento se deriva del de las tablas a las que apuntan (espacios, tickets,
# etiquetas), que si llevan la columna.
_TIPO_PROYECTO_ID = (
    "INTEGER REFERENCES proyectos(id) ON DELETE SET NULL",
    "INTEGER REFERENCES proyectos(id) ON DELETE SET NULL",
)

#: Tablas de negocio que pertenecen a un proyecto (las 34 clases con la
#: columna nueva). ``usuarios`` NO aparece: los usuarios son globales.
TABLAS_CON_PROYECTO: List[str] = [
    "adjuntos",
    "auditorias",
    "botones_tarjeta",
    "campos_personalizados",
    "catalogo_items",
    "catalogo_tipos",
    "checklist_items",
    "checklists",
    "comandos_programados",
    "comentarios",
    "ejecuciones_automatizacion",
    "ejecuciones_boton",
    "ejecuciones_comando",
    "espacios",
    "estados",
    "etapas_proyecto",
    "etiquetas",
    "historial_estados",
    "menciones_usuario",
    "notificaciones",
    "permisos_tablero",
    "reacciones",
    "reglas_automatizacion",
    "reporte_destinatarios",
    "reporte_entregas_diarias",
    "reporte_plantilla",
    "tableros",
    "ticket_dependencias",
    "ticket_etapas",
    "ticket_referencias",
    "tickets",
    "transiciones_estado",
    "valores_campo",
    "watches",
]

# Anade ``proyecto_id`` a cada tabla del proyecto, conservando el resto de
# columnas declaradas para esas mismas tablas.
for _tabla_proyecto in TABLAS_CON_PROYECTO:
    COLUMNS_TO_ADD.setdefault(_tabla_proyecto, {})["proyecto_id"] = _TIPO_PROYECTO_ID


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

# V2.009 — Índice de ``proyecto_id`` en cada tabla del proyecto. El índice NO
# lo crea el ``ALTER TABLE ADD COLUMN`` (en PostgreSQL los índices se crean
# aparte), asi que se declaran aqui. Sin el, el filtro por proyecto y el
# conteo por proyecto tendrian que recorrer la tabla entera.
INDEXES.extend(
    (
        "ix_%s_proyecto_id" % tabla,
        "CREATE INDEX IF NOT EXISTS ix_%s_proyecto_id ON %s(proyecto_id)" % (tabla, tabla),
    )
    for tabla in TABLAS_CON_PROYECTO
)

# Tablas que deben existir (si el modelo está presente, ``create_all``
# las crea automáticamente al ejecutar ``apply_migrations``). Este set
# sirve para verificar manualmente o para tooling externo.
TABLES_REQUIRED: List[str] = [
    "ticket_dependencias",
    "ticket_referencias",
]

# === V2.009 — Nulabilidad que el modelo declara y la BD puede no tener ======
# Estas columnas son NULLABLE en el modelo, pero una version anterior de la
# base de datos pudo crearlas como NOT NULL. El caso real es
# ``auditorias.usuario_id``: el servicio ``app.services.deadline_notifier``
# inserta auditorias de eventos del sistema con ``usuario_id = NULL`` y, si
# la columna sigue siendo NOT NULL, el INSERT falla con IntegrityError.
#
# Hasta V2.008 la relajacion de esa nulabilidad DEPENDIA de ejecutar a mano
# ``python -m scripts.migrar_auditoria_usuario_id_nullable``: si nadie lo
# ejecutaba en el despliegue, los triggers de SLA dejaban de registrar
# auditoria. Ahora la operacion es una migracion idempotente que se aplica en
# cada arranque.
#
# Relajar la nulabilidad es ADITIVO: no cambia ningun dato, solo permite que
# el valor sea NULL.
COLUMNAS_A_NULLABLE: List[Tuple[str, str]] = [
    ("auditorias", "usuario_id"),
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


#: Clave del cerrojo consultivo de PostgreSQL que serializa las
#: migraciones entre los servicios que arrancan a la vez (web, worker y beat).
CLAVE_CERROJO_MIGRACIONES = 7_412_009_013


def _asegurar_modelos_importados() -> None:
    """Importa el paquete de modelos para que ``Base.metadata`` los conozca.

    Sin esto, ``apply_migrations()`` ejecutado FUERA de la aplicación web
    (como script, o desde ``start.sh``) trabaja con un ``Base.metadata``
    VACÍO: ``create_all`` no crea ninguna tabla y todas las migraciones
    ``ALTER TABLE`` fallan con "no such table: ...". Dentro de la aplicación
    web el fallo no se ve porque el lifespan ya importó los modelos.

    Importar ``app.models`` (que a su vez importa todos los módulos) es la
    forma canónica de poblar el metadata.
    """
    try:
        import app.models  # noqa: F401
    except Exception as exc:  # pragma: no cover
        logger.error(
            "[migrations] No se pudieron importar los modelos: %s. "
            "Las migraciones pueden fallar por tablas inexistentes.", exc,
        )


def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
    """
    Aplica migraciones pendientes para alinear el esquema con los modelos.

    - Idempotente: puede ejecutarse en cada arranque.
    - Segura: usa `engine.begin()` para transaccionar; si algo falla, hace rollback.
    - Retorna un dict con estadísticas {applied, skipped, indexes, errors}.
    """
    _asegurar_modelos_importados()
    eng = eng or _get_default_engine()
    is_pg = eng.dialect.name == "postgresql"
    is_sqlite = eng.dialect.name == "sqlite"
    # ``schema_errors`` cuenta SOLO los fallos que dejan el esquema sin
    # alinear (creación de tablas y columnas). ``errors`` es el total e
    # incluye también las migraciones de datos, que no impiden servir.
    stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0,
             "schema_errors": 0, "tables_created": 0, "data_migrated": 0,
             "index_errors": 0, "rls": {}}

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
        stats["schema_errors"] += 1

    # 2) Añadir columnas faltantes
    with eng.begin() as conn:
        # --- V2.009: CERROJO DE MIGRACIONES -----------------------------
        # En el despliegue de Railway, ``start.sh`` ejecuta
        # ``verificar_esquema()`` en los TRES roles (web, worker y beat) a
        # la vez, y los tres aplican las migraciones sobre la MISMA base de
        # datos. Dos de ellos pueden pasar a la vez el chequeo
        # ``CREATE INDEX IF NOT EXISTS`` (que no bloquea) y los dos intentar
        # crear el mismo indice: el segundo recibe
        #
        #     duplicate key value violates unique constraint
        #     "pg_class_relname_nsp_index"
        #
        # y su TRANSACCION queda abortada, de modo que los indices que
        # quedaban por crear fallan todos con "current transaction is
        # aborted". Medido en produccion el 2026-11-14: un servicio creo 3
        # indices y fallo en los 52 restantes.
        #
        # ``pg_advisory_xact_lock`` serializa las migraciones: el primero la
        # toma y los demas esperan; cuando le toca, encuentra el esquema ya
        # alineado y no hace nada. El cerrojo se suelta solo al cerrar la
        # transaccion (COMMIT o ROLLBACK).
        if is_pg:
            try:
                conn.execute(text(
                    "SELECT pg_advisory_xact_lock(:clave)"
                ), {"clave": CLAVE_CERROJO_MIGRACIONES})
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "[migrations] no se pudo tomar el cerrojo de migraciones: %s", exc,
                )

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
                    stats["schema_errors"] += 1

        # 3) Crear índices faltantes (IF NOT EXISTS funciona en ambos motores)
        #    Un índice que no se puede crear NO es fatal (la app sirve sin
        #    él), pero el fallo tiene que quedar VISIBLE: antes se
        #    registraba con ``logger.debug`` (invisible en producción) y no
        #    se contabilizaba, de modo que un esquema al que le faltaba un
        #    índice pasaba el ``verificar_esquema`` sin dejar rastro.
        #
        #    V2.009 — CADA ÍNDICE VA EN SU PROPIO SAVEPOINT.
        #    En PostgreSQL, un error dentro de una transacción la ABORTA: los
        #    comandos siguientes fallan con "current transaction is aborted".
        #    Con el bucle entero en una sola transacción, UN índice que
        #    fallara (por ejemplo, por un nombre que ya existe en otra
        #    tabla) invalidaba los 54 restantes. Se vio en produccion el
        #    2026-11-14: 3 índices creados y 52 fallidos, entre ellos los 34
        #    ``ix_<tabla>_proyecto_id``, que son los que necesita el filtro
        #    por proyecto. Con un savepoint por índice, un fallo aislado
        #    revierte solo su propio índice.
        for name, sql in INDEXES:
            try:
                with conn.begin_nested():
                    conn.execute(text(sql))
                stats["indexes"] += 1
            except Exception as e:
                stats["index_errors"] += 1
                logger.warning(
                    "[migrations] Índice %s NO se pudo crear: %s", name, e,
                )

    # 3-bis) Row Level Security (V2.009). Inerte por defecto: solo se aplica
    #        si el flag ``RLS_HABILITADO`` esta a True, cosa que ocurre en la
    #        ventana V3 (el corte). Con el rol owner de siempre y sin FORCE,
    #        las politicas existirian pero no restringen nada.
    try:
        from app.core.config import settings as _settings

        if _settings.RLS_HABILITADO:
            from app.db.rls import aplicar_politicas_rls

            stats["rls"] = aplicar_politicas_rls(eng, TABLAS_CON_PROYECTO)
            logger.info("[migrations] RLS aplicado: %s", stats["rls"])
        else:
            stats["rls"] = {"politicas": 0, "habilitadas": 0, "forzadas": 0, "errores": 0}
    except Exception as e:
        stats["errors"] += 1
        logger.warning("[migrations] RLS no se pudo aplicar: %s", e)

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
        "[migrations] Resultado: applied=%d skipped=%d indexes=%d errors=%d "
        "schema_errors=%d data_migrated=%d index_errors=%d",
        stats["applied"], stats["skipped"], stats["indexes"], stats["errors"],
        stats["schema_errors"], stats["data_migrated"], stats["index_errors"],
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
                # `es_entrega` es NOT NULL y su default (False) es de
                # SQLAlchemy (lado Python), NO un default del servidor: un
                # INSERT raw que lo omita falla con
                # "NOT NULL constraint failed: estados.es_entrega" y el
                # estado 'Producción OK' NO se creaba en una base nueva.
                # Se inserta en FALSE; la migración 4.9 lo marca como
                # estado de entrega (su nombre normalizado está en la
                # lista de-recognized).
                if is_pg:
                    res = conn.execute(text(
                        "INSERT INTO estados (nombre, descripcion, color, orden, "
                        "es_inicial, es_final, categoria, sla_horas, archivado, "
                        "limite_wip, es_entrega, created_at, updated_at) "
                        "SELECT 'Producción OK', "
                        "       'Corrección desplegada y verificada en ambiente productivo', "
                        "       '#0d9488', COALESCE((SELECT MAX(orden)+1 FROM estados), 7), "
                        "       FALSE, TRUE, 'produccion_ok', NULL, FALSE, NULL, "
                        "       FALSE, :ts, :ts"
                    ), {"ts": ts_now})
                else:
                    res = conn.execute(text(
                        "INSERT INTO estados (nombre, descripcion, color, orden, "
                        "es_inicial, es_final, categoria, sla_horas, archivado, "
                        "limite_wip, es_entrega, created_at, updated_at) "
                        "SELECT 'Producción OK', "
                        "       'Corrección desplegada y verificada en ambiente productivo', "
                        "       '#0d9488', COALESCE((SELECT MAX(orden)+1 FROM estados), 7), "
                        "       0, 1, 'produccion_ok', NULL, 0, NULL, 0, :ts, :ts"
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

    # 4.x) V2.009 — Proyecto "Legacy" y backfill de ``proyecto_id``.
    #
    # Aditivo e idempotente:
    #   1) crea la fila del proyecto "Legacy" (id 1) si no existe;
    #   2) rellena ``proyecto_id = 1`` en todas las filas que lo tengan a NULL
    #      (o sea, todas las anteriores a este lote);
    #   3) da de alta al administrador como miembro del proyecto Legacy.
    #
    # Tras el backfill, todas las filas existentes pertenecen al proyecto
    # "Legacy", que es exactamente el conjunto de datos que habia antes: no
    # se pierde ni se modifica ningun dato de negocio, solo se anade la
    # pertenencia a un proyecto. El paso a NOT NULL (y la creacion del rol
    # sin privilegios de owner) son de la ventana V3 (el corte).
    total += _aplicar_proyecto_legacy(conn, is_pg)

    return total


#: Id del proyecto "Legacy" (el que contiene los datos preexistentes).
PROYECTO_LEGACY_ID = 1

#: Nombre del proyecto "Legacy".
NOMBRE_PROYECTO_LEGACY = "Legacy"


def _etiquetas_rol_usuario(conn, is_pg: bool) -> List[str]:
    """
    Devuelve las etiquetas REALES con las que la base de datos persiste el
    rol de los usuarios.

    Por que hace falta (V2.009)
    -------------------------
    ``usuarios.rol`` es un ENUM de PostgreSQL y SQLAlchemy persiste el
    **NOMBRE** del miembro del enum de Python (``RolUsuario.ADMINISTRADOR``),
    no su VALOR (``"administrador"``). Comparar la columna contra el literal
    ``'administrador'`` hace que PostgreSQL intente convertir ese texto a
    etiqueta del enum y falle con::

        invalid input value for enum rolusuario: "administrador"

    Ese error tumbaba el paso 3 de la migracion del proyecto Legacy. En vez de
    adivinar la etiqueta, se leen las que la base de datos usa de verdad: los
    valores distintos almacenados en la columna y, en PostgreSQL, el catalogo
    ``pg_enum``.
    """
    etiquetas: List[str] = []

    # 1) Valores realmente almacenados (funciona en ambos motores).
    sql = (
        "SELECT DISTINCT rol::text FROM usuarios WHERE rol IS NOT NULL"
        if is_pg else
        "SELECT DISTINCT rol FROM usuarios WHERE rol IS NOT NULL"
    )
    try:
        for fila in conn.execute(text(sql)).fetchall():
            if fila and fila[0] is not None:
                etiqueta = str(fila[0])
                if etiqueta not in etiquetas:
                    etiquetas.append(etiqueta)
    except Exception:  # pragma: no cover - la tabla puede no existir aun
        pass

    # 2) En PostgreSQL, el catalogo de etiquetas del tipo enum.
    if is_pg:
        try:
            for fila in conn.execute(text(
                "SELECT e.enumlabel FROM pg_type t "
                "JOIN pg_enum e ON e.enumtypid = t.oid "
                "JOIN pg_attribute a ON a.atttypid = t.oid "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = 'usuarios' AND a.attname = 'rol' "
                "AND n.nspname = current_schema() "
                "ORDER BY e.enumsortorder"
            )).fetchall():
                if fila and fila[0]:
                    etiqueta = str(fila[0])
                    if etiqueta not in etiquetas:
                        etiquetas.append(etiqueta)
        except Exception:  # pragma: no cover - depende del catalogo de PG
            pass

    return etiquetas


def _resolver_etiqueta_admin(conn, is_pg: bool) -> str:
    """
    Devuelve la etiqueta con la que el motor almacena el rol de administrador.

    Prioridad: coincidencia exacta -> etiqueta que contenga "ADMIN" -> el
    NOMBRE del miembro del enum de Python (que es lo que SQLAlchemy persiste
    por defecto en PostgreSQL y en SQLite).
    """
    etiquetas = _etiquetas_rol_usuario(conn, is_pg)

    for etiqueta in etiquetas:
        if etiqueta.strip().upper() == "ADMINISTRADOR":
            return etiqueta

    for etiqueta in etiquetas:
        if "ADMIN" in etiqueta.strip().upper():
            return etiqueta

    try:
        from app.models.usuario import RolUsuario
        return RolUsuario.ADMINISTRADOR.name
    except Exception:  # pragma: no cover
        return "ADMINISTRADOR"


def _aplicar_proyecto_legacy(conn, is_pg: bool) -> int:
    """
    Crea el proyecto "Legacy" y asigna a el todas las filas de negocio que
    todavia no tienen ``proyecto_id``.

    Es idempotente: se puede ejecutar en cada arranque. Devuelve el numero de
    filas actualizadas.

    Atomicidad (V2.009)
    --------------------
    Cada paso va en su PROPIO savepoint. Antes de V2.009 los tres pasos
    compartian un unico ``begin_nested()``: si el ultimo fallaba, PostgreSQL
    revertia el SAVEPOINT entero y con el el backfill completo (8.500 filas),
    dejando ``proyecto_id`` a NULL en todas las tablas. Ahora un fallo puntual
    (por ejemplo, que un enum no acepte la etiqueta buscada) solo revierte su
    propio paso: el resto de la migracion se aplica igual.
    """
    actualizadas = 0

    # 1) Fila del proyecto "Legacy" (savepoint propio).
    try:
        with conn.begin_nested():
            if is_pg:
                conn.execute(text(
                    "INSERT INTO proyectos (id, nombre, descripcion, plan, color, activo, "
                    "created_at, updated_at) "
                    "VALUES (:id, :nombre, :descripcion, NULL, '#6b7280', TRUE, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (id) DO NOTHING"
                ), {"id": PROYECTO_LEGACY_ID, "nombre": NOMBRE_PROYECTO_LEGACY,
                    "descripcion": "Proyecto historico: contiene los datos "
                                   "preexistentes al aislamiento por proyecto."})
            else:
                conn.execute(text(
                    "INSERT INTO proyectos (id, nombre, descripcion, plan, color, activo, "
                    "created_at, updated_at) "
                    "SELECT :id, :nombre, :descripcion, NULL, '#6b7280', 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                    "WHERE NOT EXISTS (SELECT 1 FROM proyectos WHERE id = :id)"
                ), {"id": PROYECTO_LEGACY_ID, "nombre": NOMBRE_PROYECTO_LEGACY,
                    "descripcion": "Proyecto historico: contiene los datos "
                                   "preexistentes al aislamiento por proyecto."})
    except Exception as e:
        # Sin la fila del proyecto no se puede hacer el backfill: la columna
        # ``proyecto_id`` tiene clave foranea a ``proyectos.id``.
        logger.warning(
            "[migrations] data: no se pudo crear el proyecto Legacy: %s", e,
        )
        return actualizadas

    # 2) Backfill: cada tabla en su PROPIO savepoint, para que un fallo
    #    puntual en una tabla no revierta las anteriores.
    for tabla in TABLAS_CON_PROYECTO:
        try:
            with conn.begin_nested():
                res = conn.execute(text(
                    "UPDATE %s SET proyecto_id = :pid WHERE proyecto_id IS NULL" % tabla
                ), {"pid": PROYECTO_LEGACY_ID})
                n = res.rowcount if hasattr(res, "rowcount") else 0
            if n:
                actualizadas += n
                logger.info(
                    "[migrations] data: %d filas de %s asignadas al proyecto Legacy",
                    n, tabla,
                )
        except Exception as e:
            logger.warning(
                "[migrations] data: backfill de %s fallo (aislado): %s", tabla, e,
            )

    # 3) El administrador es miembro del proyecto Legacy (savepoint propio).
    try:
        with conn.begin_nested():
            etiqueta = _resolver_etiqueta_admin(conn, is_pg)
            # El rol se filtra EN PYTHON, no en SQL: pasar un literal a una
            # columna ENUM obliga a PostgreSQL a convertirlo a etiqueta y
            # falla si no coincide exactamente. Leyendo el valor almacenado
            # no hay ninguna conversion que pueda fallar.
            filas = conn.execute(text("SELECT id, rol FROM usuarios")).fetchall()
            admines = [
                fila[0] for fila in filas
                if fila[1] is not None and "ADMIN" in str(fila[1]).strip().upper()
            ]
            ts = datetime.now(timezone.utc).isoformat()
            for usuario_id in admines:
                conn.execute(text(
                    "INSERT INTO proyecto_usuarios (proyecto_id, usuario_id, rol, created_at) "
                    "SELECT :pid, :uid, :rol, :ts WHERE NOT EXISTS ("
                    "SELECT 1 FROM proyecto_usuarios "
                    "WHERE proyecto_id = :pid AND usuario_id = :uid)"
                ), {"pid": PROYECTO_LEGACY_ID, "uid": usuario_id,
                    "rol": etiqueta.strip().lower(), "ts": ts})
        if admines:
            logger.info(
                "[migrations] data: %d administrador(es) añadidos al proyecto Legacy",
                len(admines),
            )
    except Exception as e:
        logger.warning(
            "[migrations] data: membresia del administrador en Legacy fallo (aislado): %s", e,
        )

    return actualizadas


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


def comparar_esquema_completo(eng: Optional[Engine] = None) -> List[str]:
    """
    Compara el metadata de SQLAlchemy con el esquema REAL de la base de datos.

    Por qué hace falta (V2.009)
    -------------------------
    ``report_schema_drift()`` solo mira las tablas de ``COLUMNS_TO_ADD`` (tres
    hasta V2.008). Eso hacia que el guardián de arranque fuera **fail-closed
    solo a medias**: si el modelo declaraba una columna que la base de datos
    no tenia, y esa columna no estaba en ``COLUMNS_TO_ADD``, nadie se enteraba
    y la aplicacion respondia 500 al usarla. En V2.009 el guardián compara
    TODAS las tablas del metadata.

    Qué devuelve
    ------------
    Una línea por tabla con la deriva. El formato distingue las dos señales:
    * ``<tabla>: faltan <columna>`` -> la tabla existe pero le faltan columnas
      que el modelo declara. Es la señal que debe abortar el arranque.
    * ``<tabla>: la tabla no existe en la base de datos`` -> el modelo declara
      una tabla que no esta creada.
    * ``<tabla>: OK`` -> la tabla esta alineada.

    Las tablas que existen en la base de datos pero NO en el modelo no se
    reportan: son datos historicos que la aplicacion ya no usa y borrarlas es
    una decision operativa, no una migracion.
    """
    eng = eng or _get_default_engine()
    _asegurar_modelos_importados()
    try:
        insp = inspect(eng)
        tablas_bd = set(insp.get_table_names())
    except Exception as exc:  # pragma: no cover
        logger.warning("[migrations] no se pudo inspeccionar el esquema: %s", exc)
        return []

    out: List[str] = []
    for nombre, tabla in Base.metadata.tables.items():
        if nombre not in tablas_bd:
            out.append(f"{nombre}: la tabla no existe en la base de datos")
            continue
        try:
            columnas_bd = {c["name"] for c in insp.get_columns(nombre)}
        except Exception as exc:  # pragma: no cover
            out.append(f"{nombre}: no se pudieron leer sus columnas ({exc})")
            continue
        faltan = [c.name for c in tabla.c if c.name not in columnas_bd]
        if faltan:
            out.append(f"{nombre}: faltan {', '.join(faltan)}")
        else:
            out.append(f"{nombre}: OK")
    return out


def _indice_y_tabla_de_un_index(sql: str) -> Tuple[str, str]:
    """
    Extrae el NOMBRE real del indice y su tabla del DDL.

    Ojo: la etiqueta de la tupla de ``INDEXES`` no siempre coincide con el
    nombre del indice que crea el DDL. Por ejemplo, la etiqueta
    ``ix_ref_origen`` crea en realidad ``ix_ticket_referencias_ticket_origen_id``
    y ``ix_adjuntos_comentario`` crea ``ix_adjuntos_comentario_id``. Comparar
    por la etiqueta daria un "FALTA" falso.
    """
    import re as _re

    m = _re.search(
        r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?\s+ON\s+[\"']?([A-Za-z_][A-Za-z0-9_]*)",
        sql, _re.IGNORECASE,
    )
    if m:
        return m.group(1), m.group(2)
    m2 = _re.search(r"\bON\s+[\"']?([A-Za-z_][A-Za-z0-9_]*)", sql, _re.IGNORECASE)
    return "", (m2.group(1) if m2 else "")


def comparar_indices_completo(eng: Optional[Engine] = None) -> List[str]:
    """
    Compara los indices declarados en ``INDEXES`` con los que existen de
    verdad en la base de datos.

    Por que hace falta (V2.009)
    -------------------------
    El guardian de arranque comparaba COLUMNAS, nunca indices. En produccion
    (2026-11-14) fallaron 52 de los 55 indices declarados y la aplicacion
    arranco igual: el filtro por proyecto se quedaba sin indice y las
    consultas tenian que recorrer la tabla entera, sin que nada lo dijera.

    Este comparador devuelve una linea por indice declarado que NO esta en
    su sitio:

    * ``<nombre>: FALTA (declarado sobre <tabla>)`` -> no existe.
    * ``<nombre>: COLISION (existe sobre '<otra>', el DDL lo declara sobre
      '<tabla>')`` -> el nombre ya lo usa OTRA tabla. En PostgreSQL,
      ``CREATE INDEX IF NOT EXISTS`` ignora el aviso SOLO si el indice con
      ese nombre esta en la MISMA tabla: si esta en otra, falla con
      "relation already exists".

    Los indices que estan bien NO se reportan: el resultado son solo
    problemas.
    """
    eng = eng or _get_default_engine()
    _asegurar_modelos_importados()
    try:
        insp = inspect(eng)
        indice_por_nombre: Dict[str, str] = {}
        for nombre in Base.metadata.tables:
            for idx in insp.get_indexes(nombre):
                indice_por_nombre[idx["name"]] = nombre
            for uq in insp.get_unique_constraints(nombre):
                indice_por_nombre.setdefault(uq["name"], nombre)
    except Exception as exc:  # pragma: no cover
        logger.warning("[migrations] no se pudieron inspeccionar los indices: %s", exc)
        return []

    out: List[str] = []
    for etiqueta, sql in INDEXES:
        nombre, tabla = _indice_y_tabla_de_un_index(sql)
        if not nombre:
            # DDL no reconocible: se usa la etiqueta como nombre.
            nombre = etiqueta
        real = indice_por_nombre.get(nombre)
        if real is None:
            out.append("%s: FALTA (declarado sobre %s)" % (nombre, tabla))
        elif tabla and real != tabla:
            out.append(
                "%s: COLISION (existe sobre '%s', el DDL lo declara sobre '%s')"
                % (nombre, real, tabla)
            )
    return out


def verificar_esquema(eng: Optional[Engine] = None) -> int:
    """Aplica las migraciones y comprueba que el esquema queda alineado.

    Devuelve 0 si el esquema sirve y 1 si no. Lo usa ``start.sh`` para
    abortar el arranque en vez de servir con un esquema viejo.

    Criterio de fallo (fail-closed con EVIDENCIA POSITIVA)
    ---------------------------------------------------------
    1. **Deriva de esquema**: queda alguna columna de ``COLUMNS_TO_ADD``
       que las migraciones no pudieron añadir. Es la señal directa de
       "el esquema que el código necesita no está".
    2. **Errores de esquema**: falló ``create_all`` o un ``ADD COLUMN``.

    No son motivo de fallo:
    * Errores de las migraciones **de datos** (normalización de valores,
      renombrados, ``es_entrega``). El esquema queda alineado y la
      aplicación sirve igual: abortar el arranque por ello dejaría los
      tres servicios caídos sin evitar ningún 500.
    * Una excepción inesperada **dentro de esta propia comprobación**.
      El guardián no puede ser él mismo el que tumbe el servicio: si la
      base no es alcanzable, la aplicación ya fallará por su cuenta y
      Railway la reiniciará. Aquí solo se deja constancia en el log.

    OJO: ``report_schema_drift()`` devuelve UNA LÍNEA POR TABLA, y esa
    línea dice "OK (N columnas)" cuando no hay deriva. Por eso NO se puede
    usar la lista completa como condición de fallo: hay que filtrar las
    líneas que contienen "faltan".
    """
    try:
        stats = apply_migrations(eng)
        lineas = report_schema_drift(eng)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[migrations] la comprobacion de esquema no pudo ejecutarse: %s. "
            "Se continua el arranque: el guard no debe ser el que tumbe el "
            "servicio.", exc,
        )
        return 0

    faltan = [l for l in lineas if "faltan" in l]

    # V2.009 — Guardián estricto: compara TODO el metadata con el esquema real.
    # Hasta V2.008 solo se comparaban las tablas de ``COLUMNS_TO_ADD``, de modo
    # que una columna que el modelo declarase y la base de datos no tuviera
    # pasaba desapercibida. Se activa con ``ESQUEMA_ESTRICTO`` porque un
    # guardián fail-closed sobre el esquema completo puede tumbar los tres
    # servicios si la base de datos arrastra una deriva heredada; por eso
    # primero se mide (endpoint ``/api/v1/migraciones/esquema``) y despues se
    # enciende.
    deriva_completa: List[str] = []
    try:
        from app.core.config import settings as _settings

        if _settings.ESQUEMA_ESTRICTO:
            deriva_completa = [
                l for l in comparar_esquema_completo(eng)
                if "faltan" in l or "no existe" in l
            ]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[migrations] no se pudo ejecutar la comparación estricta de esquema: %s", exc,
        )

    errores = int(stats.get("errors", 0) or 0)
    errores_esquema = int(stats.get("schema_errors", 0) or 0)
    logger.info(
        "[migrations] aplicar: aplicadas=%s omitidas=%s errores=%s "
        "errores_esquema=%s indices_fallidos=%s",
        stats.get("applied", 0), stats.get("skipped", 0), errores,
        errores_esquema, stats.get("index_errors", 0),
    )
    if stats.get("index_errors", 0):
        logger.warning(
            "[migrations] %s índice(s) NO se pudieron crear. El esquema sirve, "
            "pero esas consultas van a recorrer la tabla completa.",
            stats.get("index_errors", 0),
        )
    if faltan:
        logger.error("[migrations] DERIVA DE ESQUEMA: %s", "; ".join(faltan))
    if deriva_completa:
        logger.error(
            "[migrations] DERIVA DE ESQUEMA (comparación estricta del metadata): %s",
            "; ".join(deriva_completa),
        )
    if errores_esquema:
        logger.error(
            "[migrations] %s error(es) de esquema al aplicar las migraciones",
            errores_esquema,
        )
    if errores and not errores_esquema:
        logger.warning(
            "[migrations] %s error(es) en las migraciones de DATAS. El esquema "
            "queda alineado, se continua el arranque.", errores,
        )
    return 1 if (faltan or errores_esquema or deriva_completa) else 0


if __name__ == "__main__":
    # Permite ejecutar manualmente: `python -m app.db.migrations`
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Permitir override del engine vía env var para testing
    db_url = os.environ.get("TEST_DATABASE_URL")
    target_engine = None
    if db_url:
        from sqlalchemy import create_engine
        from app.core.config import enmascarar_url_db
        target_engine = create_engine(db_url)
        # La URL se enmascara: imprimirla en crudo exponía la contraseña de
        # la base de datos en los logs del despliegue.
        print(f"Usando engine override: {enmascarar_url_db(db_url)}")
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
