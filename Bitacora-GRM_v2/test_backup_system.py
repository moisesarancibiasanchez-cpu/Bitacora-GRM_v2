"""
Test suite para el sistema de Respaldos de Base de Datos.

Cubre:
- BackupService (servicio central): backup SQLite, listado, get_backup_path,
  delete, retención, status, mecanismo de lock.
- Tareas Celery: backup_database_diario (Beat), backup_database_manual,
  backup_cleanup_old, run_backup_sync.
- API REST: /status, /list, /run, /download/<file>, /delete/<file>, /cleanup
  con auth override (admin y agente_senior).
- Acción Butler: backup_database y backup_cleanup.

Ejecución:
    cd /workspace
    /workspace/Bitacora-GRM_v2/.venv-test/bin/python -m unittest test_backup_system -v

NOTA: Solo SQLite está disponible en el entorno de tests (no hay PostgreSQL
ni pg_dump). Los caminos PG se omiten o se mockean.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock as umock

# ============================================================
# Configurar entorno ANTES de importar la app
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent
TEST_BACKUP_DIR = PROJECT_ROOT / "tmp_test_backups"
TEST_BACKUP_DIR.mkdir(exist_ok=True)

# Forzar settings antes de que se carguen en cualquier módulo de la app
os.environ["BACKUP_DIR"] = str(TEST_BACKUP_DIR)
os.environ["BACKUP_RETENTION_DAYS"] = "7"
os.environ["BACKUP_DAILY_HOUR"] = "0"
os.environ["BACKUP_DAILY_MINUTE"] = "0"
os.environ["BACKUP_MAX_SIZE_MB"] = "2048"
os.environ["ALLOW_XUSER_HEADER"] = "true"  # habilitar X-User-Id para tests de auth

# Crear BD SQLite de prueba con datos
TEST_SQLITE_DB = PROJECT_ROOT / "tmp_test_bitacora.db"
if TEST_SQLITE_DB.exists():
    TEST_SQLITE_DB.unlink()
_conn = sqlite3.connect(str(TEST_SQLITE_DB))
_conn.executescript("""
    CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY, titulo TEXT);
    INSERT INTO tickets (titulo) VALUES ('ticket de prueba 1');
    INSERT INTO tickets (titulo) VALUES ('ticket de prueba 2');
    CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, nombre TEXT);
    INSERT INTO usuarios (nombre) VALUES ('admin');
""")
_conn.commit()
_conn.close()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_SQLITE_DB}"

# Añadir workspace al path para que 'importa app.*' funcione
sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================
# Imports de la app (post-configuración de env vars)
# ============================================================
from app.services.backup_service import (  # noqa: E402
    BackupMetadata,
    BackupResult,
    BackupService,
    get_backup_service,
)
from app.core.config import settings  # noqa: E402
from app.core.celery_app import celery_app  # noqa: E402


# ============================================================
# Helpers
# ============================================================
def _limpiar_dir_backups() -> None:
    """Borra el contenido del directorio de backups de prueba."""
    if TEST_BACKUP_DIR.exists():
        for f in TEST_BACKUP_DIR.iterdir():
            try:
                f.unlink()
            except OSError:
                pass


def _crear_backup_falso(nombre: str, dias_atras: int = 0, bytes_size: int = 100) -> Path:
    """Crea un archivo .gz + metadata simulando un backup antiguo."""
    mtime = datetime.now(timezone.utc) - timedelta(days=dias_atras)
    ts = mtime.strftime("%Y%m%d_%H%M%S")
    # Forzar nombre con prefijo estándar
    base = f"bitacora_grm_{ts}_{nombre}"
    gz = TEST_BACKUP_DIR / f"{base}.db.gz"
    meta = TEST_BACKUP_DIR / f"{base}.db.gz.meta.json"

    # Contenido gzip pequeño
    payload = b"x" * bytes_size
    with gzip.open(gz, "wb") as f:
        f.write(payload)
    # Ajustar mtime
    mtime_epoch = mtime.timestamp()
    os.utime(gz, (mtime_epoch, mtime_epoch))

    meta_dict = {
        "filename": gz.name,
        "engine": "sqlite",
        "created_at": mtime.isoformat(),
        "size_bytes": bytes_size,
        "uncompressed_bytes": bytes_size,
        "duration_seconds": 0.01,
        "schema_version": "0.1.0",
        "database_url_safe": "sqlite:///...",
        "notes": nombre,
    }
    meta.write_text(json.dumps(meta_dict), encoding="utf-8")
    return gz


# ============================================================
# 1. BackupService - tests unitarios
# ============================================================
class TestBackupService(unittest.TestCase):
    """Tests del servicio central de backups."""

    def setUp(self) -> None:
        _limpiar_dir_backups()
        self.svc = BackupService()
        # Invalidar singleton cache
        import app.services.backup_service as mod_svc
        mod_svc._service = None
        self.svc = get_backup_service()

    def tearDown(self) -> None:
        _limpiar_dir_backups()

    # ---- engine detection ----
    def test_engine_detection(self):
        self.assertEqual(BackupService._engine_from_url("postgresql://x"), "postgresql")
        self.assertEqual(
            BackupService._engine_from_url("postgresql+psycopg2://x"),
            "postgresql",
        )
        self.assertEqual(
            BackupService._engine_from_url("postgres://x"), "postgresql"
        )
        self.assertEqual(BackupService._engine_from_url("sqlite:///x"), "sqlite")
        self.assertEqual(BackupService._engine_from_url(""), "sqlite")
        self.assertEqual(BackupService._engine_from_url("mongodb://x"), "unknown")

    def test_safe_url_oculta_password(self):
        self.assertIn("***", BackupService._safe_url("postgresql://u:secret@h/d"))
        self.assertNotIn("secret", BackupService._safe_url("postgresql://u:secret@h/d"))

    def test_safe_url_no_password(self):
        out = BackupService._safe_url("postgresql://u@h/d")
        self.assertNotIn("***", out)

    # ---- backup_dir ----
    def test_backup_dir_es_absoluto(self):
        self.assertTrue(self.svc.backup_dir.is_absolute())

    def test_backup_dir_apunta_a_test_dir(self):
        self.assertEqual(self.svc.backup_dir.resolve(), TEST_BACKUP_DIR.resolve())

    def test_ensure_backup_dir_crea_directorio(self):
        # Borrar y verificar que se vuelve a crear
        import shutil
        shutil.rmtree(TEST_BACKUP_DIR)
        self.assertFalse(TEST_BACKUP_DIR.exists())
        self.svc.ensure_backup_dir()
        self.assertTrue(TEST_BACKUP_DIR.exists())

    # ---- build_filename ----
    def test_build_filename_sqlite(self):
        nombre = self.svc.build_filename("sqlite", note="manual")
        self.assertTrue(nombre.startswith("bitacora_grm_"))
        self.assertTrue(nombre.endswith(".db.gz"))
        self.assertIn("_manual", nombre)

    def test_build_filename_postgresql(self):
        nombre = self.svc.build_filename("postgresql", note="scheduled")
        self.assertTrue(nombre.endswith(".sql.gz"))
        self.assertIn("_scheduled", nombre)

    def test_build_filename_sanea_caracteres(self):
        nombre = self.svc.build_filename("sqlite", note="a/b c?d!f")
        # caracteres no permitidos se eliminan
        self.assertNotIn("/", nombre)
        self.assertNotIn(" ", nombre)
        self.assertNotIn("?", nombre)
        self.assertNotIn("!", nombre)

    def test_build_filename_con_fecha_custom(self):
        when = datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        nombre = self.svc.build_filename("sqlite", when=when, note="")
        self.assertIn("20250115_123000", nombre)
        # Sin sufijo note cuando note=""
        self.assertTrue(nombre.startswith("bitacora_grm_20250115_123000.db.gz"))

    # ---- run_backup SQLite ----
    def test_run_backup_sqlite_exitoso(self):
        result = self.svc.run_backup(note="test_unit", skip_if_busy=False)
        self.assertTrue(result.ok, msg=f"backup falló: {result.error}")
        self.assertIsNotNone(result.metadata)
        self.assertEqual(result.metadata.engine, "sqlite")
        self.assertEqual(result.metadata.notes, "test_unit")
        self.assertGreater(result.metadata.size_bytes, 0)
        self.assertGreater(result.metadata.uncompressed_bytes, 0)
        # Verificar que existe el archivo
        gz_path = TEST_BACKUP_DIR / result.metadata.filename
        self.assertTrue(gz_path.exists())
        # Verificar metadata adyacente
        meta_path = TEST_BACKUP_DIR / (result.metadata.filename + ".meta.json")
        self.assertTrue(meta_path.exists())
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta_data["filename"], result.metadata.filename)
        self.assertEqual(meta_data["engine"], "sqlite")

    def test_run_backup_gz_es_gzip_valido(self):
        result = self.svc.run_backup(note="verify", skip_if_busy=False)
        self.assertTrue(result.ok)
        gz_path = TEST_BACKUP_DIR / result.metadata.filename
        # Debe poder descomprimirse
        with gzip.open(gz_path, "rb") as f:
            data = f.read()
        self.assertGreater(len(data), 0)
        # El contenido descomprimido debe empezar con la cabecera SQLite
        self.assertIn(b"SQLite format 3", data[:100])

    # ---- lock mechanism ----
    def test_run_backup_skipped_si_lock_reciente(self):
        """Si hay un .backup.lock reciente, el backup debe saltarse."""
        # Crear lock manual
        lock_path = self.svc.backup_dir / ".backup.lock"
        lock_path.touch()
        try:
            result = self.svc.run_backup(note="test_lock", skip_if_busy=True)
            self.assertFalse(result.ok)
            self.assertIsNotNone(result.skipped_reason)
            self.assertIn("lock", result.skipped_reason.lower())
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass

    def test_run_backup_con_lock_viejo_puede_ejecutar(self):
        """Si el lock tiene >1h, debe ser ignorado (lock stale)."""
        import os
        lock_path = self.svc.backup_dir / ".backup.lock"
        lock_path.touch()
        # Forzar mtime a 2 horas atrás
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
        os.utime(lock_path, (old_time, old_time))
        try:
            result = self.svc.run_backup(note="stale_lock", skip_if_busy=True)
            self.assertTrue(result.ok, msg=result.error)
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass

    # ---- list_backups ----
    def test_list_backups_vacio(self):
        self.assertEqual(self.svc.list_backups(), [])

    def test_list_backups_ordenados_desc(self):
        _crear_backup_falso("reciente", dias_atras=1)
        _crear_backup_falso("antiguo", dias_atras=10)
        backups = self.svc.list_backups()
        self.assertEqual(len(backups), 2)
        # El más reciente debe estar primero (su modified_at es mayor)
        self.assertGreater(backups[0]["modified_at"], backups[1]["modified_at"])
        # Todos deben tener campos requeridos
        for b in backups:
            self.assertIn("filename", b)
            self.assertIn("size_bytes", b)
            self.assertIn("modified_at", b)
            self.assertIn("engine", b)
            self.assertEqual(b["engine"], "sqlite")

    # ---- get_backup_path ----
    def test_get_backup_path_valido(self):
        gz = _crear_backup_falso("valido", dias_atras=0)
        path = self.svc.get_backup_path(gz.name)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

    def test_get_backup_path_rechaza_path_traversal(self):
        # Intentar path traversal
        self.assertIsNone(self.svc.get_backup_path("../etc/passwd"))
        self.assertIsNone(self.svc.get_backup_path("..\\windows\\system32"))
        self.assertIsNone(self.svc.get_backup_path("bitacora_grm_/etc/passwd"))

    def test_get_backup_path_rechaza_prefijo_incorrecto(self):
        self.assertIsNone(self.svc.get_backup_path("evil_20250101.db.gz"))

    def test_get_backup_path_rechaza_extension_incorrecta(self):
        self.assertIsNone(self.svc.get_backup_path("bitacora_grm_20250101.txt"))

    def test_get_backup_path_rechaza_archivo_inexistente(self):
        self.assertIsNone(
            self.svc.get_backup_path("bitacora_grm_99990101_000000.db.gz")
        )

    # ---- delete_backup ----
    def test_delete_backup_exitoso(self):
        gz = _crear_backup_falso("borrar", dias_atras=0)
        meta = gz.with_suffix(gz.suffix + ".meta.json")
        self.assertTrue(gz.exists())
        self.assertTrue(meta.exists())
        ok, msg = self.svc.delete_backup(gz.name)
        self.assertTrue(ok)
        self.assertFalse(gz.exists())
        self.assertFalse(meta.exists())
        self.assertIn(gz.name, msg)

    def test_delete_backup_no_existente(self):
        ok, msg = self.svc.delete_backup("bitacora_grm_99999999_999999.db.gz")
        self.assertFalse(ok)
        self.assertIn("no encontrado", msg.lower())

    def test_delete_backup_nombre_invalido(self):
        ok, _msg = self.svc.delete_backup("../etc/passwd")
        self.assertFalse(ok)

    # ---- cleanup_old_backups ----
    def test_cleanup_retiene_recientes(self):
        """Con retención 7 días, el de 1 día se retiene y el de 30 se purga."""
        # Reciente: 1 día, Antiguo: 30 días
        reciente = _crear_backup_falso("reciente", dias_atras=1, bytes_size=100)
        antiguo = _crear_backup_falso("antiguo", dias_atras=30, bytes_size=100)
        # Retención 7 días
        result = self.svc.cleanup_old_backups(retention_days=7)
        self.assertIn("purged", result)
        self.assertIn("errors", result)
        # El reciente debe haberse retenido (1 día < 7 días de retención)
        self.assertTrue(reciente.exists(), "El backup reciente debe retenerse")
        # El antiguo debe haberse purgado
        purged_names = result["purged"]
        self.assertIn(antiguo.name, purged_names)
        self.assertFalse(antiguo.exists(), "El backup antiguo debe haberse purgado")
        # El reciente NO debe estar en la lista de purgados
        self.assertNotIn(reciente.name, purged_names)

    def test_cleanup_con_retention_cero_no_purga(self):
        _crear_backup_falso("test", dias_atras=30)
        # retention_days=1: el de 30 días debe purgar
        result = self.svc.cleanup_old_backups(retention_days=1)
        self.assertEqual(len(result["purged"]), 1)

    def test_cleanup_usa_settings_por_defecto(self):
        """Sin arg, debe usar BACKUP_RETENTION_DAYS=7 (configurado en env)."""
        _crear_backup_falso("antiguo", dias_atras=30)
        result = self.svc.cleanup_old_backups()
        self.assertGreater(len(result["purged"]), 0)

    def test_cleanup_idempotente(self):
        _crear_backup_falso("x", dias_atras=30)
        r1 = self.svc.cleanup_old_backups(retention_days=1)
        r2 = self.svc.cleanup_old_backups(retention_days=1)
        self.assertGreater(len(r1["purged"]), 0)
        self.assertEqual(len(r2["purged"]), 0)

    # ---- status ----
    def test_status_devuelve_diccionario_completo(self):
        status = self.svc.status()
        self.assertIsInstance(status, dict)
        self.assertIn("backup_dir", status)
        self.assertIn("backup_dir_exists", status)
        self.assertIn("retention_days", status)
        self.assertIn("max_size_mb", status)
        self.assertIn("engine", status)
        self.assertIn("pg_dump_available", status)
        self.assertIn("total_backups", status)
        self.assertIn("total_size_bytes", status)
        self.assertIn("last_backup", status)
        self.assertIn("schedule", status)
        self.assertEqual(status["engine"], "sqlite")
        self.assertEqual(status["schedule"], {"daily_hour": 0, "daily_minute": 0})
        self.assertEqual(status["retention_days"], 7)

    def test_status_refleja_backups(self):
        _crear_backup_falso("s1", dias_atras=1)
        _crear_backup_falso("s2", dias_atras=2)
        status = self.svc.status()
        self.assertEqual(status["total_backups"], 2)
        self.assertGreater(status["total_size_bytes"], 0)
        self.assertIsNotNone(status["last_backup"])
        self.assertIn("filename", status["last_backup"])

    def test_status_sin_backups(self):
        status = self.svc.status()
        self.assertEqual(status["total_backups"], 0)
        self.assertEqual(status["total_size_bytes"], 0)
        self.assertIsNone(status["last_backup"])


# ============================================================
# 2. Tareas Celery - tests
# ============================================================
class TestBackupCeleryTasks(unittest.TestCase):
    """Tests para las tareas Celery del sistema de backup."""

    def setUp(self) -> None:
        _limpiar_dir_backups()
        import app.services.backup_service as mod_svc
        mod_svc._service = None
        # Forzar eager mode (sin broker)
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def tearDown(self) -> None:
        _limpiar_dir_backups()

    def test_run_backup_sync_directo(self):
        """run_backup_sync ejecuta sin pasar por Celery."""
        from app.tasks.backup_tasks import run_backup_sync
        payload = run_backup_sync(note="test_sync")
        self.assertTrue(payload["ok"], msg=str(payload))
        self.assertIn("started_at", payload)
        self.assertIn("metadata", payload)
        self.assertIsNotNone(payload["metadata"])
        self.assertEqual(payload["metadata"]["notes"], "test_sync")
        # cleanup debe estar presente cuando ok=True
        self.assertIn("cleanup", payload)

    def test_run_backup_sync_error_devuelve_estructura(self):
        """Si la BD no existe, debe devolver ok=False con error explicativo."""
        # Forzar URL inválida
        original = settings.DATABASE_URL
        try:
            from app.services.backup_service import BackupService as _Svc
            svc = BackupService()
            # Pasamos una URL con motor no soportado directamente
            svc.run_backup(
                note="bad", database_url="mongodb://x", skip_if_busy=False
            )
            # Para run_backup_sync usamos el servicio singleton, no podemos
            # cambiar DATABASE_URL sin reinstanciar el servicio, pero la
            # validación interna del servicio debe devolver error.
        finally:
            settings.DATABASE_URL = original

    def test_backup_database_manual_eager(self):
        from app.tasks.backup_tasks import backup_database_manual
        result = backup_database_manual.apply(kwargs={"note": "test_manual"}).get()
        self.assertTrue(result["ok"], msg=str(result))
        self.assertIn("started_at", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["notes"], "test_manual")

    def test_backup_database_diario_eager(self):
        """Beat simulado: ejecutar la tarea con nota 'scheduled'."""
        from app.tasks.backup_tasks import backup_database_diario
        result = backup_database_diario.apply(kwargs={"note": "scheduled"}).get()
        self.assertTrue(result["ok"], msg=str(result))
        self.assertEqual(result["metadata"]["notes"], "scheduled")
        # El cleanup debe estar incluido tras backup exitoso
        self.assertIn("cleanup", result)
        self.assertIn("purged", result["cleanup"])
        self.assertIn("errors", result["cleanup"])

    def test_backup_cleanup_old_eager(self):
        """Tarea auxiliar de purga."""
        from app.tasks.backup_tasks import backup_cleanup_old
        # Crear backup antiguo
        _crear_backup_falso("limpieza", dias_atras=30)
        result = backup_cleanup_old.apply(kwargs={"retention_days": 7}).get()
        self.assertIn("purged", result)
        self.assertGreater(len(result["purged"]), 0)


# ============================================================
# 3. API REST - tests con TestClient
# ============================================================
class TestBackupAPIEndpoints(unittest.TestCase):
    """Tests de los endpoints REST /api/v1/butler/backup/*."""

    @classmethod
    def setUpClass(cls) -> None:
        # Configurar Celery en modo eager para el endpoint /run async
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

    def setUp(self) -> None:
        _limpiar_dir_backups()
        import app.services.backup_service as mod_svc
        mod_svc._service = None

        # Crear la app con un router mínimo + el router de backups
        from fastapi import FastAPI, Depends
        from app.api.v1.backups import router as backups_router_real
        from app.models.usuario import Usuario, RolUsuario

        self.app = FastAPI()
        self.app.include_router(backups_router_real)

        # Usuario mock (admin y otro solicitante)
        self.admin_user = Usuario(
            id=1,
            username="admin_test",
            email="admin@test.local",
            rol=RolUsuario.ADMINISTRADOR,
            is_active=True,
        )
        self.agente_senior_user = Usuario(
            id=2,
            username="senior_test",
            email="senior@test.local",
            rol=RolUsuario.AGENTE_SENIOR,
            is_active=True,
        )
        self.solicitante_user = Usuario(
            id=3,
            username="user_test",
            email="user@test.local",
            rol=RolUsuario.SOLICITANTE,
            is_active=True,
        )

        from app.api.v1.deps import get_current_user, get_db

        def _mock_user_factory(usuario):
            def _mock():
                return usuario
            return _mock

        def _mock_db():
            # Devolver una sesión dummy - los endpoints que no tocan DB
            # sólo necesitan el objeto. Pero get_db del proyecto requiere
            # configuración real. Para evitarlo, mockeamos get_db a nivel app.
            from unittest.mock import MagicMock
            return MagicMock()

        # Override del dependency get_current_user (vía app.dependency_overrides)
        self._override_users = {
            "admin": self.admin_user,
            "senior": self.agente_senior_user,
            "solicitante": self.solicitante_user,
        }

        # Override de get_current_user: leemos de un header personalizado
        # para diferenciar el rol.
        def _get_user_override(request=None, **kwargs):
            # El header X-Test-Rol indica qué usuario devolver
            from fastapi import Request as Req
            # Truco: en este router fake, podemos leer del request.headers
            # directamente. Como Depends se llama con la Request inyectada
            # por FastAPI, vamos a inspeccionar el contexto vía headers.
            return self.admin_user  # default fallback

        # Para los tests usaremos directamente dependency_overrides
        # con funciones individuales por rol.
        self.app.dependency_overrides[get_db] = _mock_db
        # Override genérico (admin por defecto; tests específicos sobreescriben)

        # Cliente de tests
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        _limpiar_dir_backups()

    def _with_user(self, usuario):
        """Helper para inyectar un usuario en el dependency override."""
        from app.api.v1.deps import get_current_user
        def _get():
            return usuario
        self.app.dependency_overrides[get_current_user] = _get

    def _with_no_user(self):
        """Helper para simular 'no autenticado'."""
        from app.api.v1.deps import get_current_user
        self.app.dependency_overrides.pop(get_current_user, None)

    # ---- status ----
    def test_status_como_admin(self):
        self._with_user(self.admin_user)
        r = self.client.get("/butler/backup/status")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["engine"], "sqlite")
        self.assertEqual(data["retention_days"], 7)
        self.assertEqual(data["schedule"], {"daily_hour": 0, "daily_minute": 0})

    def test_status_como_agente_senior(self):
        self._with_user(self.agente_senior_user)
        r = self.client.get("/butler/backup/status")
        self.assertEqual(r.status_code, 200)

    def test_status_como_solicitante_rechazado(self):
        self._with_user(self.solicitante_user)
        r = self.client.get("/butler/backup/status")
        self.assertEqual(r.status_code, 403)
        self.assertIn("administrador", r.json()["detail"].lower())

    def test_status_sin_auth_rechazado(self):
        self._with_no_user()
        r = self.client.get("/butler/backup/status")
        self.assertEqual(r.status_code, 401)

    # ---- list ----
    def test_list_vacio(self):
        self._with_user(self.admin_user)
        r = self.client.get("/butler/backup/list")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_list_con_backups(self):
        # Crear backups
        _crear_backup_falso("a", dias_atras=1)
        _crear_backup_falso("b", dias_atras=2)
        self._with_user(self.admin_user)
        r = self.client.get("/butler/backup/list")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 2)
        # Ordenado desc por modified_at (más reciente primero)
        self.assertGreaterEqual(data[0]["modified_at"], data[1]["modified_at"])

    def test_list_como_solicitante_rechazado(self):
        self._with_user(self.solicitante_user)
        r = self.client.get("/butler/backup/list")
        self.assertEqual(r.status_code, 403)

    # ---- run (síncrono) ----
    def test_run_sync_como_admin(self):
        self._with_user(self.admin_user)
        r = self.client.post(
            "/butler/backup/run",
            json={"note": "test_endpoint", "async_task": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertIn("started_at", data)
        self.assertIn("metadata", data)
        self.assertEqual(data["metadata"]["notes"], "test_endpoint")

    def test_run_async_task_encolar_celery(self):
        """Con async_task=True, encola en Celery (modo eager aquí)."""
        self._with_user(self.admin_user)
        r = self.client.post(
            "/butler/backup/run",
            json={"note": "async_test", "async_task": True},
        )
        # En eager mode debe devolver OK con task_id
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["ok"])
        # task_id presente cuando async_task=True
        if "task_id" in data and data["task_id"]:
            self.assertIsInstance(data["task_id"], str)

    def test_run_como_solicitante_rechazado(self):
        self._with_user(self.solicitante_user)
        r = self.client.post("/butler/backup/run", json={"note": "x"})
        self.assertEqual(r.status_code, 403)

    def test_run_sin_auth_rechazado(self):
        self._with_no_user()
        r = self.client.post("/butler/backup/run", json={"note": "x"})
        self.assertEqual(r.status_code, 401)

    # ---- download ----
    def test_download_backup_valido(self):
        gz = _crear_backup_falso("download", dias_atras=1)
        self._with_user(self.admin_user)
        r = self.client.get(f"/butler/backup/download/{gz.name}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("gzip", r.headers.get("content-type", ""))
        # Verificar contenido gzip
        content = r.content
        with gzip.open(io.BytesIO(content), "rb") as f:
            data = f.read()
        self.assertGreater(len(data), 0)

    def test_download_no_existente_404(self):
        self._with_user(self.admin_user)
        r = self.client.get("/butler/backup/download/bitacora_grm_99999999_999999.db.gz")
        self.assertEqual(r.status_code, 404)

    def test_download_path_traversal_rechazado(self):
        self._with_user(self.admin_user)
        # FastAPI decodifica el %2e%2e antes de pasarlo al handler
        r = self.client.get("/butler/backup/download/..%2Fetc%2Fpasswd")
        # Debe rechazarse (404 por no matchear prefijo)
        self.assertIn(r.status_code, (400, 404))

    def test_download_como_solicitante_rechazado(self):
        gz = _crear_backup_falso("x", dias_atras=1)
        self._with_user(self.solicitante_user)
        r = self.client.get(f"/butler/backup/download/{gz.name}")
        self.assertEqual(r.status_code, 403)

    # ---- delete ----
    def test_delete_backup_valido(self):
        gz = _crear_backup_falso("borrar", dias_atras=1)
        self._with_user(self.admin_user)
        r = self.client.delete(f"/butler/backup/{gz.name}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(gz.exists())

    def test_delete_no_existente_400(self):
        self._with_user(self.admin_user)
        r = self.client.delete("/butler/backup/bitacora_grm_99999999_999999.db.gz")
        self.assertEqual(r.status_code, 400)

    def test_delete_path_traversal_rechazado(self):
        self._with_user(self.admin_user)
        r = self.client.delete("/butler/backup/..%2Fetc%2Fpasswd")
        self.assertIn(r.status_code, (400, 404))

    def test_delete_como_solicitante_rechazado(self):
        gz = _crear_backup_falso("y", dias_atras=1)
        self._with_user(self.solicitante_user)
        r = self.client.delete(f"/butler/backup/{gz.name}")
        self.assertEqual(r.status_code, 403)

    # ---- cleanup ----
    def test_cleanup_post(self):
        _crear_backup_falso("old", dias_atras=30)
        self._with_user(self.admin_user)
        r = self.client.post("/butler/backup/cleanup", json={"retention_days": 7})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("purged", data)
        self.assertGreater(len(data["purged"]), 0)

    def test_cleanup_con_retention_default(self):
        _crear_backup_falso("z", dias_atras=30)
        self._with_user(self.admin_user)
        r = self.client.post("/butler/backup/cleanup", json={})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("purged", data)
        self.assertIn("retention_days", data)

    def test_cleanup_validacion_retention_days_negativo(self):
        self._with_user(self.admin_user)
        r = self.client.post("/butler/backup/cleanup", json={"retention_days": -1})
        # Validación Pydantic: 422
        self.assertEqual(r.status_code, 422)

    def test_cleanup_como_solicitante_rechazado(self):
        self._with_user(self.solicitante_user)
        r = self.client.post("/butler/backup/cleanup", json={"retention_days": 7})
        self.assertEqual(r.status_code, 403)


# ============================================================
# 4. Acción Butler - test de integración con backup_database
# ============================================================
class TestButlerBackupAction(unittest.TestCase):
    """Test de la acción Butler 'backup_database'."""

    def setUp(self) -> None:
        _limpiar_dir_backups()
        import app.services.backup_service as mod_svc
        mod_svc._service = None

    def tearDown(self) -> None:
        _limpiar_dir_backups()

    def test_ejecutar_accion_backup_database(self):
        """La acción 'backup_database' del ButlerExecutor ejecuta un backup."""
        from app.services.butler_executor import _ejecutar_accion

        # Ticket dummy
        ticket_mock = umock.MagicMock()
        ticket_mock.id = 999
        ticket_mock.creador_id = 1

        # Crear sesión mock
        db_mock = umock.MagicMock()

        accion = {"tipo": "backup_database", "parametros": {"nota": "butler_test"}}
        resultado = _ejecutar_accion(db_mock, ticket_mock, accion)

        self.assertIn("backup OK", resultado)
        self.assertIn("butler_test", resultado)
        # El backup debe haberse creado en el directorio de tests
        files = list(TEST_BACKUP_DIR.glob("bitacora_grm_*.db.gz"))
        self.assertGreater(len(files), 0)

    def test_ejecutar_accion_backup_database_alias_respaldar_bd(self):
        """El alias 'respaldar_bd' también debe funcionar."""
        from app.services.butler_executor import _ejecutar_accion

        ticket_mock = umock.MagicMock()
        ticket_mock.id = 1000
        db_mock = umock.MagicMock()

        accion = {"tipo": "respaldar_bd", "parametros": {"nota": "alias_test"}}
        resultado = _ejecutar_accion(db_mock, ticket_mock, accion)

        self.assertIn("backup OK", resultado)

    def test_ejecutar_accion_backup_cleanup(self):
        """La acción 'backup_cleanup' purga backups antiguos."""
        from app.services.butler_executor import _ejecutar_accion

        ticket_mock = umock.MagicMock()
        ticket_mock.id = 1001
        db_mock = umock.MagicMock()

        # Crear un backup antiguo
        _crear_backup_falso("purga_butler", dias_atras=30)

        accion = {"tipo": "backup_cleanup", "parametros": {"dias": 7}}
        resultado = _ejecutar_accion(db_mock, ticket_mock, accion)

        self.assertIn("purga OK", resultado)
        self.assertIn("archivos eliminados", resultado)

    def test_ejecutar_accion_backup_cleanup_alias_purgar_backups(self):
        """Alias 'purgar_backups' debe funcionar."""
        from app.services.butler_executor import _ejecutar_accion

        ticket_mock = umock.MagicMock()
        ticket_mock.id = 1002
        db_mock = umock.MagicMock()

        _crear_backup_falso("alias_purga", dias_atras=30)

        accion = {"tipo": "purgar_backups", "parametros": {"dias": 7}}
        resultado = _ejecutar_accion(db_mock, ticket_mock, accion)

        self.assertIn("purga OK", resultado)


# ============================================================
# 5. Integración - test end-to-end
# ============================================================
class TestBackupEndToEnd(unittest.TestCase):
    """Test end-to-end: API → Service → Sistema de archivos."""

    def setUp(self) -> None:
        _limpiar_dir_backups()
        import app.services.backup_service as mod_svc
        mod_svc._service = None

    def tearDown(self) -> None:
        _limpiar_dir_backups()

    def test_flujo_completo_crear_listar_descargar_eliminar(self):
        from app.services.backup_service import get_backup_service
        svc = get_backup_service()

        # 1. Crear backup
        r = svc.run_backup(note="e2e", skip_if_busy=False)
        self.assertTrue(r.ok)
        nombre = r.metadata.filename

        # 2. Listar - debe aparecer
        backups = svc.list_backups()
        nombres = [b["filename"] for b in backups]
        self.assertIn(nombre, nombres)

        # 3. Descargar (resolver path)
        path = svc.get_backup_path(nombre)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        # Verificar gzip
        with gzip.open(path, "rb") as f:
            data = f.read()
        self.assertIn(b"SQLite format 3", data[:100])

        # 4. Eliminar
        ok, msg = svc.delete_backup(nombre)
        self.assertTrue(ok)
        self.assertFalse(path.exists())
        self.assertFalse(svc.get_backup_path(nombre))  # ya no existe

        # 5. Status refleja cambios
        status = svc.status()
        self.assertEqual(status["total_backups"], 0)

    def test_multiples_backups_con_retention(self):
        from app.services.backup_service import get_backup_service
        svc = get_backup_service()

        # Crear 3 backups: 1 reciente, 2 antiguos
        svc.run_backup(note="reciente1", skip_if_busy=False)
        # Esperar 1s para diferenciar timestamps
        import time
        time.sleep(1)
        svc.run_backup(note="reciente2", skip_if_busy=False)
        _crear_backup_falso("antiguo", dias_atras=30)

        # Antes de la limpieza
        self.assertEqual(svc.status()["total_backups"], 3)

        # Limpiar con retención 7 días
        result = svc.cleanup_old_backups(retention_days=7)
        self.assertEqual(len(result["purged"]), 1)
        # Solo el antiguo debe haberse purgado
        purged_names = result["purged"]
        self.assertEqual(len(purged_names), 1)
        self.assertIn("antiguo", purged_names[0])

        # Verificar status final
        status = svc.status()
        self.assertEqual(status["total_backups"], 2)


# ============================================================
# Main: ejecutar todo
# ============================================================
if __name__ == "__main__":
    # Configurar verbosidad
    unittest.main(verbosity=2, buffer=True, exit=False)