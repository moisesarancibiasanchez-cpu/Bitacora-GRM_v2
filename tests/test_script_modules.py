"""
Runner pytest para los módulos de test escritos como *scripts*.

Los módulos listados en ``SCRIPTS`` no son módulos pytest: ejecutan toda su
lógica en tiempo de importación y terminan con ``sys.exit(codigo)``. Recolectarlos
directamente provoca dos problemas reales:

1. Si una aserción falla, el ``SystemExit`` lanzado **durante la recolección**
   aborta la sesión completa de pytest (``INTERNALERROR``, 0 tests ejecutados).
2. ``app/db/session.py`` crea el ``engine`` SQLAlchemy a nivel de módulo, por
   lo que en un único proceso todos los módulos comparten (y pisan) la misma
   base de datos.

Este runner los ejecuta en un **subproceso independiente**, conservando:

* su base de datos SQLite aislada,
* su contrato de código de salida (``0`` = todo OK, ``1`` = fallo),
* la salida en consola completa, que se adjunta al reporte de fallo.

Con esto, ``pytest tests/`` ejecuta la suite completa sin abortarse.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

# Módulos estilo script: cada uno necesita su propio proceso y su propia BD.
SCRIPTS = [
    "cli_smoke_test.py",
    "test_bulk_update_gar_ri.py",
    "test_reporte_entregas.py",
]


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_modulo(script: str) -> None:
    """Ejecuta un módulo de test estilo script en un subproceso aislado.

    Falla el test si el subproceso devuelve un código distinto de 0.
    """
    ruta = TESTS_DIR / script
    assert ruta.exists(), f"No existe el módulo de test esperado: {ruta}"

    # El subproceso escribe UTF-8 (los scripts imprimen acentos y símbolos
    # como '✓'). Con ``text=True`` a secas, Python decodifica con la
    # codificación local de la plataforma: en una consola Windows eso es
    # cp1252 y la lectura revienta con UnicodeDecodeError. Se fija UTF-8
    # explícitamente en ambos extremos (emisor y receptor) y ``errors=
    # "replace"`` evita que una salida no decodificable tumbe la suite.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # Los scripts importan ``app.*``, así que la raíz del repo tiene que estar
    # en el ``sys.path`` del subproceso. No se da por supuesto que el paquete
    # esté instalado (``pip install -e .``) ni que ``PYTHONPATH`` llegue al
    # hijo: en un interprete embebido con ``python311._pth`` el ``PYTHONPATH``
    # se ignora y el directorio de trabajo NO se anade a ``sys.path``. Por eso
    # el hijo se lanza con un arranque explicito que inserta la raiz y ejecuta
    # el script como ``__main__`` (igual que ``python <script>``).
    bootstrap = (
        "import sys, runpy; "
        "sys.path.insert(0, {raiz!r}); "
        "runpy.run_path({script!r}, run_name='__main__')"
    ).format(raiz=str(RAIZ), script=str(ruta))

    proc = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        env=env,
    )

    if proc.returncode != 0:
        pytest.fail(
            f"{script} terminó con código de salida {proc.returncode}\n"
            f"---------- stdout (últimas 8000 líneas) ----------\n"
            f"{proc.stdout[-8000:]}\n"
            f"---------- stderr (últimas 4000 líneas) ----------\n"
            f"{proc.stderr[-4000:]}"
        )
