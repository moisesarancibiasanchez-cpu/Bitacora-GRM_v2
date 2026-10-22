"""
Servicio de respaldos de Base de Datos.

Soporta dos motores:

- **PostgreSQL** (producción): usa el binario `pg_dump` si está disponible
  en el PATH.  Hace dump en formato ``plain`` (SQL) y lo comprime con gzip.
  Si ``pg_dump`` no está instalado, cae a un fallback con ``psycopg2`` que
  ejecuta ``COPY ... TO STDOUT`` por tabla.

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
        """Fallback psycopg2: genera SQL manualmente."""
        try:
            import psycopg2  # type: ignore
            import psycopg2.extensions  # type: ignore
        except ImportError as e:
            raise FileNotFoundError(
                "pg_dump no disponible y psycopg2 no instalado"
            ) from e

        conn = psycopg2.connect(db_url)
        conn.set_session(readonly=True, autocommit=True)
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [r[0] for r in cur.fetchall()]
            lines: List[str] = []
            lines.append("-- Bitácora GRM backup (psycopg2 fallback)")
            lines.append(f"-- Generado: {datetime.now(timezone.utc).isoformat()}")
            lines.append("")
            for t in tables:
                cur.execute(f'SELECT * FROM "{t}"')
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                if not rows:
                    continue
                col_list = ", ".join(f'"{c}"' for c in cols)
                lines.append(f"-- Table: {t} ({len(rows)} filas)")
                for row in rows:
                    vals = []
                    for v in row:
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        elif isinstance(v, bool):
                            vals.append("TRUE" if v else "FALSE")
                        elif isinstance(v, (bytes, memoryview)):
                            vals.append(f"'\\\\x{v.hex()}'")
                        else:
                            s = str(v).replace("'", "''")
                            vals.append(f"'{s}'")
                    lines.append(
                        f"INSERT INTO \"{t}\" ({col_list}) VALUES ({', '.join(vals)});"
                    )
                lines.append("")
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
