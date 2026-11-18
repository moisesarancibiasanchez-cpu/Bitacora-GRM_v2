"""
Servicio de respaldos de Base de Datos.

Soporta dos motores:

- **PostgreSQL** (producción): usa el binario `pg_dump` si está disponible
  en el PATH.  Hace dump en formato ``plain`` (SQL) y lo comprime con gzip.
  Si ``pg_dump`` no está instalado, cae a un fallback con ``psycopg2`` que
  reconstruye el dump desde ``pg_catalog`` (DDL + datos + índices +
  constraints + secuencias) en un formato **restaurable**.

- **SQLite** (desarrollo/demo): usa la API nativa ``sqlite3.Connection.backup()``
  que crea un snapshot consistente en otra conexión.

Características:
- Política de retención (cantidad de días configurable).
- Metadata en JSON adyacente al .gz (tamaño, fecha, motor, duración).
- Paths siempre absolutos (anchored a la raíz del proyecto).
- Tolerante a filesystem read-only (loggea warning en vez de abortar).
- Idempotente: ``cleanup_old_backups`` se puede llamar sin riesgos.

Patrón de nombres:
    bitacora_grm_YYYYMMDD_HHMMSS.sql.gz    (PostgreSQL)
    bitacora_grm_YYYYMMDD_HHMMSS.db.gz     (SQLite)

Este servicio es consumido por:
- Tarea Celery Beat programada (app.tasks.backup_tasks)
- Endpoint manual /api/v1/butler/backup/run (API REST)
- Acción Butler "backup_database" (reglas de automatización)
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings


logger = logging.getLogger(__name__)


# ============================================================
# Estructuras de datos
# ============================================================

@dataclass
class BackupMetadata:
    """Información de un backup almacenada en .meta.json adyacente al .gz."""
    filename: str                 # nombre del .gz (sin ruta)
    engine: str                   # "postgresql" | "sqlite"
    created_at: str               # ISO 8601 UTC
    size_bytes: int               # tamaño del .gz
    uncompressed_bytes: int       # tamaño del dump sin comprimir
    duration_seconds: float
    schema_version: str = ""      # versión del esquema (informativo)
    database_url_safe: str = ""   # URL sin password
    notes: str = ""               # ej: "manual", "scheduled", "trigger:butler"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackupResult:
    """Resultado de ejecutar un backup (éxito o fallo)."""
    ok: bool
    metadata: Optional[BackupMetadata] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }


# ============================================================
# Servicio principal
# ============================================================

def _pg_literal(v: Any, tipo: str = "") -> str:
    """
    Literal SQL de PostgreSQL para un valor Python.

    ``tipo`` es el tipo DECLARADO de la columna (la salida de
    ``format_type``). HACE FALTA para las columnas ``json`` y ``jsonb``:
    psycopg2 convierte esas columnas en objetos Python (un dict, un str, un
    bool...) y un literal SQL escrito a pelo no siempre es JSON valido.

    Lo que se vio en produccion el 2026-11-18 al restaurar el backup: un
    string JSON (``"incidencia"``) salia como ``'incidencia'`` (sin las
    comillas del JSON), un booleano salia como ``TRUE`` y un null JSON como
    ``NULL``. Los tres los rechazaba la columna al restaurar::

        ERROR: invalid input syntax for type json

    Con el tipo a la vista, el valor se serializa SIEMPRE con ``json.dumps``:
    ``"incidencia"``, ``true``, ``null``, ``{"a": 1}``...
    """
    if tipo in ("json", "jsonb"):
        if v is None:
            return "NULL"
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:
            return "'NaN'"
        if v == float("inf"):
            return "'Infinity'"
        if v == float("-inf"):
            return "'-Infinity'"
        return repr(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        # formato hex de bytea: un solo backslash -> '\x0a1b'
        return "'\\x" + bytes(v).hex() + "'"
    if isinstance(v, datetime):
        return "'" + v.isoformat(sep=" ") + "'"
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        return "ARRAY[" + ", ".join(_pg_literal(x) for x in v) + "]"
    if isinstance(v, dict):
        return "'" + json.dumps(
            v, ensure_ascii=False).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


class BackupService:
    """Servicio central de respaldos.

    Diseñado como singleton ligero (sin estado mutable propio).
    """

    # ------------------------------------------------------------------
    # Propiedades públicas
    # ------------------------------------------------------------------
    @property
    def backup_dir(self) -> Path:
        """Directorio de backups, siempre absoluto."""
        raw = settings.BACKUP_DIR or "backups"
        if os.path.isabs(raw):
            return Path(raw)
        # Anclar a la raíz del proyecto (3 niveles arriba de services/)
        project_root = Path(__file__).resolve().parents[2]
        return (project_root / raw).resolve()

    @property
    def retention_days(self) -> int:
        return int(settings.BACKUP_RETENTION_DAYS)

    @property
    def max_size_mb(self) -> int:
        return int(settings.BACKUP_MAX_SIZE_MB)

    # ------------------------------------------------------------------
    # Detección del motor de BD
    # ------------------------------------------------------------------
    @staticmethod
    def _engine_from_url(url: str) -> str:
        """Devuelve 'postgresql' o 'sqlite' según la URL de BD."""
        if not url:
            return "sqlite"
        u = url.lower()
        if u.startswith("postgresql") or u.startswith("postgres"):
            return "postgresql"
        if u.startswith("sqlite"):
            return "sqlite"
        return "unknown"

    @staticmethod
    def _safe_url(url: str) -> str:
        """Devuelve la URL ocultando el password (para metadata)."""
        if not url:
            return ""
        # postgresql+psycopg2://user:pass@host:port/db
        return re.sub(r"(:[^:@/]+)@", r":***@", url)

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------
    def ensure_backup_dir(self) -> Path:
        """Crea el directorio de backups si no existe. Retorna la ruta."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            return self.backup_dir
        except OSError as e:
            logger.warning("No se pudo crear %s: %s", self.backup_dir, e)
            # Devolvemos la ruta igualmente (puede que ya exista en modo read-only)
            return self.backup_dir

    def build_filename(self, engine: str, when: Optional[datetime] = None,
                       note: str = "") -> str:
        """Genera el nombre de archivo estándar para el backup."""
        when = when or datetime.now(timezone.utc)
        ts = when.strftime("%Y%m%d_%H%M%S")
        ext = "sql" if engine == "postgresql" else "db"
        suffix = ""
        if note:
            safe = re.sub(r"[^a-zA-Z0-9_-]", "", note)[:32]
            if safe:
                suffix = f"_{safe}"
        return f"bitacora_grm_{ts}{suffix}.{ext}.gz"

    def run_backup(self, note: str = "", database_url: Optional[str] = None,
                   skip_if_busy: bool = True) -> BackupResult:
        """Ejecuta un backup completo.

        Args:
            note: nota corta (ej: "manual", "scheduled", "butler").
            database_url: override de la URL de BD (default: settings.get_database_url()).
            skip_if_busy: si True y ya hay un backup en curso (lock), sale sin error.

        Returns:
            BackupResult con metadata si tuvo éxito.
        """
        db_url = database_url or settings.get_database_url()
        engine = self._engine_from_url(db_url)
        if engine == "unknown":
            return BackupResult(ok=False, error=f"Motor de BD no soportado: {db_url}")

        # Lock cooperativo para evitar backups concurrentes.
        lock_path = self.backup_dir / ".backup.lock"
        if skip_if_busy and lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age < 3600:  # lock de menos de 1h
                return BackupResult(
                    ok=False,
                    skipped_reason=f"Backup en curso (lock de {int(age)}s)",
                )

        self.ensure_backup_dir()
        filename = self.build_filename(engine, note=note)
        target = self.backup_dir / filename
        metadata_path = self.backup_dir / (filename + ".meta.json")

        lock_path.touch()
        try:
            logger.info("[BACKUP] Iniciando backup de BD %s -> %s", engine, target)
            t0 = time.time()

            if engine == "postgresql":
                size_uncompressed = self._backup_postgresql(db_url, target)
            else:
                size_uncompressed = self._backup_sqlite(db_url, target)

            if not target.exists():
                return BackupResult(ok=False, error="Dump no generó archivo")

            size_gz = target.stat().st_size
            duration = round(time.time() - t0, 3)

            # Sanity check: tamaño máximo
            if size_gz > self.max_size_mb * 1024 * 1024:
                target.unlink(missing_ok=True)
                return BackupResult(
                    ok=False,
                    error=f"Backup excede {self.max_size_mb} MB; eliminado por seguridad",
                )

            meta = BackupMetadata(
                filename=filename,
                engine=engine,
                created_at=datetime.now(timezone.utc).isoformat(),
                size_bytes=size_gz,
                uncompressed_bytes=size_uncompressed,
                duration_seconds=duration,
                schema_version=settings.APP_VERSION,
                database_url_safe=self._safe_url(db_url),
                notes=note,
            )
            try:
                metadata_path.write_text(
                    json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning("No se pudo escribir metadata %s: %s", metadata_path, e)

            logger.info(
                "[BACKUP] OK %s (%.2fs, %d bytes gz, %d bytes uncompressed)",
                filename, duration, size_gz, size_uncompressed,
            )
            return BackupResult(ok=True, metadata=meta)

        except FileNotFoundError as e:
            return BackupResult(ok=False, error=f"Dependencia no encontrada: {e}")
        except Exception as e:
            logger.exception("[BACKUP] Error durante el backup")
            return BackupResult(ok=False, error=str(e)[:500])
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Backends específicos
    # ------------------------------------------------------------------
    def _backup_postgresql(self, db_url: str, target: Path) -> int:
        """Backup de PostgreSQL vía pg_dump (comprimido en gzip)."""
        # Parsear la URL
        # postgresql+psycopg2://user:pass@host:port/db?sslmode=...
        url_clean = db_url.replace("postgresql+psycopg2://", "postgresql://")
        from urllib.parse import urlparse
        u = urlparse(url_clean)
        db = (u.path or "/").lstrip("/")
        if not db:
            raise ValueError("DATABASE_URL sin nombre de base de datos")

        env = os.environ.copy()
        if u.password:
            env["PGPASSWORD"] = u.password

        pg_dump_bin = shutil.which("pg_dump")
        if pg_dump_bin:
            # Camino rápido: pg_dump + gzip
            cmd = [
                pg_dump_bin,
                "-h", u.hostname or "localhost",
                "-p", str(u.port or 5432),
                "-U", u.username or "postgres",
                "-d", db,
                "--no-owner",
                "--no-privileges",
                "--clean",
                "--if-exists",
            ]
            logger.info("[BACKUP] Ejecutando pg_dump...")
            uncompressed_bytes = 0
            with target.open("wb") as gz_f:
                with gzip.GzipFile(fileobj=gz_f, mode="wb", compresslevel=6) as gz:
                    proc = subprocess.run(
                        cmd, env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=True,
                    )
                    gz.write(proc.stdout)
                    uncompressed_bytes = len(proc.stdout)
            return uncompressed_bytes

        # Fallback: dump vía psycopg2 (más lento pero portable)
        logger.warning("[BACKUP] pg_dump no encontrado, usando fallback psycopg2")
        return self._backup_postgresql_python(db_url, target)

    def _backup_postgresql_python(self, db_url: str, target: Path) -> int:
        """Fallback psycopg2: genera un dump SQL COMPLETO y restaurable.

        En producción ``pg_dump`` no está disponible en la imagen del
        contenedor, así que el dump se reconstruye a mano.  Un fichero con
        sólo ``INSERT`` **no se puede restaurar** (no hay tablas donde
        insertar) y además pierde las tablas sin filas, por lo que aquí se
        emite un dump completo y en un orden válido para ``psql``:

            1. Cabecera + ``SET`` (client_encoding, standard_conforming_strings,
               search_path).
            2. ``CREATE TYPE`` (enums) y ``CREATE SEQUENCE`` (columnas serial).
            3. ``CREATE TABLE`` de TODAS las tablas (también las vacías).
            4. ``INSERT`` con los datos de las tablas que tienen filas.
            5. ``ALTER TABLE ... ADD CONSTRAINT`` (PRIMARY KEY / UNIQUE / CHECK).
            6. ``CREATE INDEX`` de los índices no ligados a un constraint.
            7. ``ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`` (al final:
               las PK/UNIQUE ya existen, así que no hay problemas de orden
               ni con dependencias circulares entre tablas).
            8. ``setval`` de las secuencias, para que los ``id`` autogenerados
               no choquen con los datos restaurados.

        El DDL se reconstruye desde ``pg_catalog`` (la BD real), NO desde el
        metadata de SQLAlchemy: para un backup la fuente de verdad es la BD.

        Returns:
            Número de bytes del payload SIN comprimir (lo que espera el
            llamante para la metadata).
        """
        try:
            import psycopg2  # type: ignore
            import psycopg2.extensions  # type: ignore
        except ImportError as e:
            raise FileNotFoundError(
                "pg_dump no disponible y psycopg2 no instalado"
            ) from e

        # psycopg2 no entiende el esquema SQLAlchemy "postgresql+psycopg2://"
        dsn = db_url.replace("postgresql+psycopg2://", "postgresql://")
        dsn = dsn.replace("postgres+psycopg2://", "postgresql://")

        conn = psycopg2.connect(dsn)
        conn.set_client_encoding("UTF8")
        conn.set_session(readonly=True, autocommit=True)
        try:
            cur = conn.cursor()

            def qi(name: str) -> str:
                """Identificador de PostgreSQL entrecomillado."""
                return '"' + str(name).replace('"', '""') + '"'

            def lit(v: Any, tipo: str = "") -> str:
                """Literal SQL de PostgreSQL para un valor Python."""
                return _pg_literal(v, tipo)

            schema = "public"
            qschema = qi(schema)

            # ------------------------------------------------------------
            # Metadatos reales de la BD (pg_catalog)
            # ------------------------------------------------------------
            cur.execute("SELECT version(), current_database(), current_user")
            pg_version, db_name, db_user = cur.fetchone()
            cur.execute("SELECT current_setting('server_version_num')")
            server_version = cur.fetchone()[0]

            cur.execute("""
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                 ORDER BY c.relname
            """)
            tables: List[str] = [r[0] for r in cur.fetchall()]

            cur.execute("""
                SELECT c.relname, a.attname,
                       format_type(a.atttypid, a.atttypmod),
                       a.attnotnull, pg_get_expr(d.adbin, d.adrelid),
                       a.attidentity, a.attgenerated
                  FROM pg_attribute a
                  JOIN pg_class c ON c.oid = a.attrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                  LEFT JOIN pg_attrdef d
                         ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                   AND a.attnum > 0 AND NOT a.attisdropped
                 ORDER BY c.relname, a.attnum
            """)
            cols_by_table: Dict[str, List[Dict[str, Any]]] = {}
            for tname, cname, ctype, notnull, defexpr, identity, generated \
                    in cur.fetchall():
                cols_by_table.setdefault(tname, []).append({
                    "name": cname,
                    "type": ctype,
                    "notnull": bool(notnull),
                    "default": defexpr,
                    "identity": identity or "",
                    "generated": generated or "",
                })

            # Enums (tipos que usa el modelo: p.ej. rol de usuario)
            cur.execute("""
                SELECT t.typname, e.enumlabel
                  FROM pg_type t
                  JOIN pg_enum e ON e.enumtypid = t.oid
                  JOIN pg_namespace n ON n.oid = t.typnamespace
                 WHERE n.nspname = 'public'
                 ORDER BY t.typname, e.enumsortorder
            """)
            enum_labels: Dict[str, List[str]] = {}
            for tname, label in cur.fetchall():
                enum_labels.setdefault(tname, []).append(label)

            # Constraints (PK / UNIQUE / CHECK / EXCLUDE / FK)
            cur.execute("""
                SELECT t.relname, c.conname, c.contype,
                       pg_get_constraintdef(c.oid)
                  FROM pg_constraint c
                  JOIN pg_class t ON t.oid = c.conrelid
                  JOIN pg_namespace n ON n.oid = t.relnamespace
                 WHERE n.nspname = 'public'
                   AND c.contype IN ('p', 'u', 'c', 'x', 'f')
                 ORDER BY t.relname, c.conname
            """)
            constraints = cur.fetchall()

            # Índices que NO respaldan un constraint (los de PK/UNIQUE los
            # crea el propio ADD CONSTRAINT)
            cur.execute("""
                SELECT t.relname, pg_get_indexdef(x.indexrelid)
                  FROM pg_index x
                  JOIN pg_class i ON i.oid = x.indexrelid
                  JOIN pg_class t ON t.oid = x.indrelid
                  JOIN pg_namespace n ON n.oid = t.relnamespace
                  LEFT JOIN pg_constraint c ON c.conindid = i.oid
                 WHERE n.nspname = 'public' AND c.oid IS NULL
                   AND NOT x.indisprimary
                 ORDER BY t.relname, i.relname
            """)
            indexes = cur.fetchall()

            # Secuencias y su columna propietaria
            cur.execute("""
                SELECT sequencename, data_type, start_value, min_value,
                       max_value, increment_by, cycle, cache_size, last_value
                  FROM pg_sequences
                 WHERE schemaname = 'public'
                 ORDER BY sequencename
            """)
            seq_by_name: Dict[str, Dict[str, Any]] = {
                r[0]: {
                    "data_type": r[1], "start": r[2], "min": r[3], "max": r[4],
                    "inc": r[5], "cycle": bool(r[6]), "cache": r[7],
                    "last": r[8],
                }
                for r in cur.fetchall()
            }

            cur.execute("""
                SELECT c.relname, t.relname, a.attname, a.attidentity
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                  JOIN pg_depend d ON d.objid = c.oid
                                 AND d.deptype IN ('a', 'i')
                  JOIN pg_class t ON t.oid = d.refobjid
                  JOIN pg_namespace tn ON tn.oid = t.relnamespace
                  JOIN pg_attribute a ON a.attrelid = d.refobjid
                                     AND a.attnum = d.refobjsubid
                 WHERE c.relkind = 'S' AND n.nspname = 'public'
                   AND tn.nspname = 'public'
                 ORDER BY c.relname
            """)
            # (seq, tabla, columna, identidad)
            seq_owner = cur.fetchall()

            # Objetos que el fallback NO puede reproducir (vistas, vistas
            # materializadas, funciones, particiones): se avisa por log.
            cur.execute("""
                SELECT c.relkind, count(*)
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public'
                   AND (c.relkind IN ('v', 'm', 'f') OR c.relispartition)
                 GROUP BY c.relkind ORDER BY c.relkind
            """)
            uncovered = cur.fetchall()
            if uncovered:
                logger.warning(
                    "[BACKUP] Objetos no incluidos en el dump (vistas/matviews/"
                    "funciones/particiones): %s", uncovered,
                )

            # Tablas con ROW LEVEL SECURITY: el dump no reproduce las
            # políticas, y si el rol no es el dueño la lectura puede venir
            # filtrada.  Se avisa para que quede constancia.
            cur.execute("""
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relrowsecurity
                 ORDER BY c.relname
            """)
            rls_tables = [r[0] for r in cur.fetchall()]
            if rls_tables:
                logger.warning(
                    "[BACKUP] Tablas con ROW LEVEL SECURITY (el dump no "
                    "reproduce las políticas): %s", rls_tables,
                )

            # ------------------------------------------------------------
            # Emisión del dump
            # ------------------------------------------------------------
            header: List[str] = []
            types_s: List[str] = []
            seqs_s: List[str] = []
            tables_s: List[str] = []
            data_s: List[str] = []
            constr_s: List[str] = []
            index_s: List[str] = []
            fk_s: List[str] = []
            seq_end_s: List[str] = []

            # (2a) Tipos ENUM: las columnas tipadas los necesitan antes.
            if enum_labels:
                types_s.append("-- ENUM types")
                for tname, labels in enum_labels.items():
                    vals = ", ".join(lit(x) for x in labels)
                    types_s.append(
                        f"CREATE TYPE {qschema}.{qi(tname)} AS ENUM ({vals});"
                    )
                types_s.append("")

            # (2b) Secuencias: las columnas SERIAL las referencian por
            # nextval('seq'::regclass) y la secuencia debe existir ANTES
            # del CREATE TABLE.  Las de las columnas IDENTITY las crea el
            # propio CREATE TABLE, así que se excluyen.
            identity_seqs = {s[0] for s in seq_owner if s[3]}
            if seq_by_name:
                seqs_s.append("-- Sequences")
                for sname, sdata in seq_by_name.items():
                    if sname in identity_seqs:
                        continue
                    seqs_s.append(
                        f"CREATE SEQUENCE IF NOT EXISTS {qschema}.{qi(sname)} "
                        f"AS {sdata['data_type']} "
                        f"START WITH {sdata['start']} "
                        f"INCREMENT BY {sdata['inc']} "
                        f"MINVALUE {sdata['min']} MAXVALUE {sdata['max']} "
                        f"CACHE {sdata['cache']} "
                        f"{'CYCLE' if sdata['cycle'] else 'NO CYCLE'};"
                    )
                seqs_s.append("")

            # (3) CREATE TABLE de TODAS las tablas (incluidas las vacías).
            tables_s.append("-- Esquema (CREATE TABLE)")
            for t in tables:
                cols = cols_by_table.get(t, [])
                if not cols:
                    logger.warning(
                        "[BACKUP] Tabla '%s' sin columnas visibles; se omite", t,
                    )
                    continue
                defs: List[str] = []
                for c in cols:
                    d = f"{qi(c['name'])} {c['type']}"
                    if c["generated"]:
                        d += f" GENERATED ALWAYS AS ({c['default']}) STORED"
                    elif c["identity"]:
                        d += (
                            " GENERATED ALWAYS AS IDENTITY"
                            if c["identity"] == "a"
                            else " GENERATED BY DEFAULT AS IDENTITY"
                        )
                    elif c["default"]:
                        d += f" DEFAULT {c['default']}"
                    if c["notnull"]:
                        d += " NOT NULL"
                    defs.append("    " + d)
                tables_s.append(f"CREATE TABLE {qschema}.{qi(t)} (")
                tables_s.append(",\n".join(defs))
                tables_s.append(");")
                tables_s.append("")

            # (4) Datos: INSERT sólo para las tablas que tienen filas.
            data_s.append("-- Datos")
            tables_with_data = 0
            for t in tables:
                all_cols = cols_by_table.get(t, [])
                cols = [c for c in all_cols if not c["generated"]]
                if not cols:
                    continue
                col_list = ", ".join(qi(c["name"]) for c in cols)
                cur.execute(
                    f"SELECT {col_list} FROM {qschema}.{qi(t)}"
                )
                rows = cur.fetchall()
                if not rows:
                    continue
                tables_with_data += 1
                # Las columnas IDENTITY ALWAYS no admiten valor explícito
                # sin OVERRIDING SYSTEM VALUE.
                overriding = ""
                if any(c["identity"] == "a" for c in all_cols):
                    overriding = " OVERRIDING SYSTEM VALUE"
                data_s.append(f"-- {t}: {len(rows)} filas")
                col_types = [c.get("type", "") for c in cols]
                for row in rows:
                    vals = ", ".join(
                        lit(v, col_types[i]) for i, v in enumerate(row)
                    )
                    data_s.append(
                        f"INSERT INTO {qschema}.{qi(t)} ({col_list})"
                        f"{overriding} VALUES ({vals});"
                    )
                data_s.append("")

            # (5) PK / UNIQUE / CHECK / EXCLUDE (antes de las FK).
            constr_s.append("-- Constraints (PRIMARY KEY / UNIQUE / CHECK)")
            for tname, cname, ctype, cdef in constraints:
                if ctype == "f":
                    continue
                constr_s.append(
                    f"ALTER TABLE {qschema}.{qi(tname)} "
                    f"ADD CONSTRAINT {qi(cname)} {cdef};"
                )
            constr_s.append("")

            # (6) Índices sueltos.
            if indexes:
                index_s.append("-- Índices")
                for tname, idef in indexes:
                    index_s.append(idef + ";")
                index_s.append("")

            # (7) Claves foráneas AL FINAL: las PK/UNIQUE ya existen y por
            # tanto no hay dependencias circulares que bloqueen el restore.
            fk_s.append("-- Claves foráneas (al final, tras PK/UNIQUE/índices)")
            for tname, cname, ctype, cdef in constraints:
                if ctype != "f":
                    continue
                fk_s.append(
                    f"ALTER TABLE {qschema}.{qi(tname)} "
                    f"ADD CONSTRAINT {qi(cname)} {cdef};"
                )
            fk_s.append("")

            # (8) Secuencias: setval al final para que los id autogenerados
            # continuen donde los dejó la tabla y no choquen.
            seq_end_s.append("-- Secuencias (setval)")
            for sname, tname, cname, ident in seq_owner:
                if not ident:
                    # Las secuencias de columnas IDENTITY ya están
                    # vinculadas a su columna: "OWNED BY" sobre ellas es
                    # un error ("cannot change ownership of identity
                    # sequence"); las SERIAL sí lo necesitan.
                    seq_end_s.append(
                        f"ALTER SEQUENCE {qschema}.{qi(sname)} "
                        f"OWNED BY {qschema}.{qi(tname)}.{qi(cname)};"
                    )
                last = seq_by_name.get(sname, {}).get("last")
                max_expr = (
                    f"COALESCE((SELECT MAX({qi(cname)}) "
                    f"FROM {qschema}.{qi(tname)}), 0)"
                )
                if last is not None:
                    # Se conserva la posición real de la secuencia (igual
                    # que pg_dump) sin quedar por debajo del MAX(id)
                    # restaurado: los id autogenerados no chocan.
                    value_expr = f"GREATEST({last}, {max_expr}, 1)"
                    called = "true"
                else:
                    value_expr = f"GREATEST({max_expr}, 1)"
                    called = f"EXISTS (SELECT 1 FROM {qschema}.{qi(tname)})"
                seq_end_s.append(
                    f"SELECT setval('{qschema}.{qi(sname)}'::regclass, "
                    f"{value_expr}, {called});"
                )
            for sname, sdata in seq_by_name.items():
                if sname in identity_seqs or sname in {s[0] for s in seq_owner}:
                    continue
                last = sdata["last"]
                seq_end_s.append(
                    f"SELECT setval('{qschema}.{qi(sname)}'::regclass, "
                    f"{last if last is not None else sdata['start']}, "
                    f"{'true' if last is not None else 'false'});"
                )
            seq_end_s.append("")

            header.append(
                "-- Bitácora GRM - backup PostgreSQL "
                "(fallback psycopg2: dump RESTAURABLE)"
            )
            header.append(
                f"-- Generado: {datetime.now(timezone.utc).isoformat()}"
            )
            header.append(f"-- Servidor: {pg_version}")
            header.append(f"-- server_version_num: {server_version}")
            header.append(f"-- Base de datos: {db_name} (usuario: {db_user})")
            header.append(
                f"-- Tablas: {len(tables)} (con datos: {tables_with_data})"
            )
            header.append(
                "-- El DDL se reconstruye desde pg_catalog (la BD real)."
            )
            header.append("")
            header.append("SET client_encoding = 'UTF8';")
            header.append("SET standard_conforming_strings = on;")
            header.append(f"SET search_path = {schema};")
            header.append("")

            lines: List[str] = []
            lines.extend(header)
            lines.extend(types_s)
            lines.extend(seqs_s)
            lines.extend(tables_s)
            lines.extend(data_s)
            lines.extend(constr_s)
            lines.extend(index_s)
            lines.extend(fk_s)
            lines.extend(seq_end_s)

            payload = "\n".join(lines).encode("utf-8")
            with target.open("wb") as gz_f:
                with gzip.GzipFile(fileobj=gz_f, mode="wb", compresslevel=6) as gz:
                    gz.write(payload)
            return len(payload)
        finally:
            conn.close()

    def _backup_sqlite(self, db_url: str, target: Path) -> int:
        """Backup de SQLite vía sqlite3.Connection.backup() + gzip."""
        # sqlite:///./path o sqlite:////absolute/path
        if db_url.startswith("sqlite:////"):
            db_path = db_url[len("sqlite:///"):]
        elif db_url.startswith("sqlite:///"):
            db_path = db_url[len("sqlite:///"):]
            if not db_path.startswith("/"):
                # sqlite:///./x.db -> ./x.db
                pass
        else:
            db_path = db_url.replace("sqlite:///", "", 1)

        if not os.path.isabs(db_path):
            project_root = Path(__file__).resolve().parents[2]
            db_path = str((project_root / db_path).resolve())

        if not os.path.exists(db_path):
            raise FileNotFoundError(f"SQLite DB no encontrada: {db_path}")

        # sqlite3.Connection.backup() hace un snapshot consistente en chunks.
        src = sqlite3.connect(db_path)
        tmp_path = self.backup_dir / (target.name + ".tmp.db")
        try:
            dst = sqlite3.connect(str(tmp_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
            # Comprimir
            with open(tmp_path, "rb") as raw, target.open("wb") as gz_f:
                with gzip.GzipFile(fileobj=gz_f, mode="wb", compresslevel=6) as gz:
                    shutil.copyfileobj(raw, gz)
            size_uncompressed = tmp_path.stat().st_size
            return size_uncompressed
        finally:
            src.close()
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Listado, descarga, borrado
    # ------------------------------------------------------------------
    def list_backups(self) -> List[Dict[str, Any]]:
        """Lista los backups disponibles ordenados por fecha descendente."""
        if not self.backup_dir.exists():
            return []
        items: List[Dict[str, Any]] = []
        for path in sorted(self.backup_dir.glob("bitacora_grm_*.gz")):
            stat = path.stat()
            meta_path = path.with_suffix(path.suffix + ".meta.json")
            meta: Dict[str, Any] = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            items.append({
                "filename": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "engine": meta.get("engine", "unknown"),
                "duration_seconds": meta.get("duration_seconds"),
                "schema_version": meta.get("schema_version", ""),
                "notes": meta.get("notes", ""),
                "metadata_path": meta_path.name if meta_path.exists() else None,
            })
        items.sort(key=lambda x: x["modified_at"], reverse=True)
        return items

    def get_backup_path(self, filename: str) -> Optional[Path]:
        """Resuelve la ruta absoluta de un backup (con validación anti-path-traversal)."""
        # Defensa: rechazar nombres con separadores o '..'
        if "/" in filename or "\\" in filename or ".." in filename:
            return None
        if not filename.startswith("bitacora_grm_"):
            return None
        if not (filename.endswith(".sql.gz") or filename.endswith(".db.gz")):
            return None
        target = self.backup_dir / filename
        try:
            target.resolve().relative_to(self.backup_dir.resolve())
        except ValueError:
            return None
        if not target.exists():
            return None
        return target

    def delete_backup(self, filename: str) -> Tuple[bool, str]:
        """Elimina un backup y su metadata asociada."""
        path = self.get_backup_path(filename)
        if not path:
            return False, f"Backup '{filename}' no encontrado o inválido"
        try:
            path.unlink(missing_ok=True)
            meta_path = path.with_suffix(path.suffix + ".meta.json")
            meta_path.unlink(missing_ok=True)
            return True, f"Backup '{filename}' eliminado"
        except OSError as e:
            return False, f"No se pudo eliminar: {e}"

    def cleanup_old_backups(self, retention_days: Optional[int] = None) -> Dict[str, Any]:
        """Purga backups más viejos que ``retention_days`` (default=settings)."""
        days = retention_days if retention_days is not None else self.retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        purged: List[str] = []
        errors: List[str] = []
        if not self.backup_dir.exists():
            return {"purged": [], "errors": [], "cutoff": cutoff.isoformat()}
        for path in list(self.backup_dir.glob("bitacora_grm_*.gz")):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    ok, _ = self.delete_backup(path.name)
                    if ok:
                        purged.append(path.name)
                    else:
                        errors.append(path.name)
            except OSError as e:
                errors.append(f"{path.name}: {e}")
        logger.info(
            "[BACKUP] Limpieza de retención: purgados=%d, errores=%d, cutoff=%s",
            len(purged), len(errors), cutoff.isoformat(),
        )
        return {
            "purged": purged,
            "errors": errors,
            "cutoff": cutoff.isoformat(),
            "retention_days": days,
        }

    # ------------------------------------------------------------------
    # Diagnóstico
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Información de diagnóstico del sistema de backups."""
        backups = self.list_backups()
        total_size = sum(b["size_bytes"] for b in backups)
        last = backups[0] if backups else None
        return {
            "backup_dir": str(self.backup_dir),
            "backup_dir_exists": self.backup_dir.exists(),
            "backup_dir_writable": os.access(self.backup_dir, os.W_OK)
            if self.backup_dir.exists() else False,
            "retention_days": self.retention_days,
            "max_size_mb": self.max_size_mb,
            "engine": self._engine_from_url(settings.get_database_url()),
            "pg_dump_available": shutil.which("pg_dump") is not None,
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "last_backup": last,
            "schedule": {
                "daily_hour": int(settings.BACKUP_DAILY_HOUR),
                "daily_minute": int(settings.BACKUP_DAILY_MINUTE),
            },
        }


# ============================================================
# Singleton perezoso
# ============================================================
_service: Optional[BackupService] = None


def get_backup_service() -> BackupService:
    """Singleton lazy del BackupService."""
    global _service
    if _service is None:
        _service = BackupService()
    return _service
