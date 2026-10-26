"""
Configuración compartida de la suite de tests (pytest).

Por qué existe este archivo
---------------------------
Antes de su existencia, ``pytest tests/`` abortaba la sesión **completa**
con ``INTERNALERROR`` y ``0 tests collected``. Las causas eran tres, todas
estructurales (no bugs de la aplicación):

1. ``tests/test_reporte_entregas.py`` y ``tests/cli_smoke_test.py`` ejecutan
   su lógica en **tiempo de importación** y terminan con ``sys.exit(1)`` si una
   aserción falla. Un ``SystemExit`` lanzado durante la recolección aborta
   *toda* la sesión de pytest, no sólo ese archivo.
2. ``tests/test_bulk_update_gar_ri.py`` hacía lo mismo (``sys.exit(1)``) y no
   contenía ninguna función ``test_*``, por lo que pytest no recolectaba nada
   (exit code 5 = "no tests ran").
3. Todos los módulos estilo script fijan su propia ``DATABASE_URL`` *antes*
   de importar ``app``, pero ``app/db/session.py`` crea el ``engine`` a nivel
   de módulo. En un único proceso gana el primer import: los módulos
   siguientes terminan operando sobre la base de datos de otro test (o, peor,
   sobre la base de datos de desarrollo).

Solución aplicada
-----------------
* Los tres módulos estilo script se **excluyen de la recolección** con
  ``collect_ignore`` y se ejecutan en un **subproceso propio** desde
  ``tests/test_script_modules.py``. Así conservan su base de datos aislada y su
  contrato de código de salida (``0`` = OK, ``1`` = fallo) sin poder abortar
  la sesión de pytest.
* ``DATABASE_URL`` se fuerza aquí, **antes de cualquier import de ``app``**, a
  una SQLite nueva y desechable bajo ``tests/tmp/``. Así, ningún test puede
  escribir sobre la base de datos de desarrollo, de CI o de producción,
  aunque el entorno traiga una ``DATABASE_URL`` real.
* Se fijan valores de entorno seguros para el arranque de la app en tests
  (``SECRET_KEY`` real, ``AUTO_INIT_DB`` apagado, sin usuarios demo).

Los módulos que sí se recolectan de forma nativa:
    * ``test_timezone_cl.py``    → unittest puro, sin base de datos.
    * ``test_trello_features.py``→ casos ``@pytest.mark.parametrize``.
    * ``test_script_modules.py`` → este runner de subprocesos.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# --- 1. Rutas --------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# --- 2. Base de datos de la suite -----------------------------------------
# El motor SQLAlchemy se crea a nivel de módulo (app/db/session.py), por lo
# que el valor debe fijarse ANTES de importar la app. Nunca debe respetarse
# una DATABASE_URL externa: la suite siempre usa un fichero SQLite nuevo,
# vacio y disposable bajo tests/tmp/.
TMP_DIR = RAIZ / "tests" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
db_fd, db_path = tempfile.mkstemp(
    prefix="pytest_suite_", suffix=".sqlite", dir=str(TMP_DIR)
)
os.close(db_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace("\\", "/")

# --- 3. Entorno de arranque seguro ----------------------------------------
# ``SECRET_KEY`` real (la app aborta en producción con una clave vacía) y
# sin auto-init ni usuarios demo, para que los tests no muten datos reales.
#
# ``DEBUG`` debe quedar en ``true`` en los tests: ``app/api/v1/auth.py`` crea
# la cookie de sesión con ``secure=not settings.DEBUG``. Con ``DEBUG=false``
# la cookie se marca ``Secure`` y ``httpx`` NO la reenvía al ``TestClient``
# (que usa el esquema ``http://testserver``), por lo que todas las peticiones
# autenticadas responderían 401.
os.environ.setdefault(
    "SECRET_KEY", "clave-solo-para-tests-nunca-usar-en-produccion-0123456789"
)
os.environ.setdefault("AUTO_INIT_DB", "false")
os.environ.setdefault("SEED_DEMO_USERS", "false")
os.environ.setdefault("DEBUG", "true")

# --- 4. Módulos estilo script ---------------------------------------------
# Se ejecutan en subproceso (ver ``tests/test_script_modules.py``).
# ``collect_ignore`` sólo aplica a la recolección por directorio: invocar
# explícitamente ``pytest tests/test_reporte_entregas.py`` sigue funcionando.
collect_ignore = [
    "cli_smoke_test.py",
    "test_bulk_update_gar_ri.py",
    "test_reporte_entregas.py",
]


# --- 5. Limpieza de la base temporal -------------------------------------
# La base creada arriba es un recurso exclusivo de esta sesión de pytest. Al
# terminar se cierran las sesiones y los engines que pudieron quedar abiertos
# y se eliminan SQLite y sus archivos auxiliares. No se toca ninguna otra base
# ni ningún fichero del repositorio.
@pytest.fixture(scope="session", autouse=True)
def _cleanup_suite_database():
    yield

    for module in list(sys.modules.values()):
        archivo = str(getattr(module, "__file__", "") or "")
        if not archivo.endswith("test_trello_features.py"):
            continue
        sesion = getattr(module, "db", None)
        if sesion is not None:
            sesion.close()
        motor = getattr(module, "engine_test", None)
        if motor is not None:
            motor.dispose()

    try:
        from app.db.session import engine as motor_app

        motor_app.dispose()
    except (ImportError, AttributeError):
        pass

    ruta_sqlite = Path(db_path)
    for sufijo in ("", "-wal", "-shm"):
        ruta_auxiliar = Path(str(ruta_sqlite) + sufijo)
        if ruta_auxiliar.exists():
            ruta_auxiliar.unlink()
