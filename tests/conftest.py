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
* ``DATABASE_URL`` se fija aquí, **antes de cualquier import de ``app``**, de
  modo que ningún test pueda escribir sobre la base de datos de desarrollo
  (``bitacora_grm.db``). Si el entorno ya trae una ``DATABASE_URL`` explícita
  (CI, Railway, etc.) se respeta; en caso contrario se usa una SQLite
  desechable.
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
from pathlib import Path

# --- 1. Rutas --------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# --- 2. Base de datos de la suite -----------------------------------------
# El motor SQLAlchemy se crea a nivel de módulo (app/db/session.py), por lo
# que el valor debe fijarse ANTES de importar la app. Nunca debe apuntar a la
# base de datos de desarrollo.
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./test_pytest_suite.db"

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
