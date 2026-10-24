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

    proc = subprocess.run(
        [sys.executable, str(ruta)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=900,
        env=os.environ.copy(),
    )

    if proc.returncode != 0:
        pytest.fail(
            f"{script} terminó con código de salida {proc.returncode}\n"
            f"---------- stdout (últimas 8000 líneas) ----------\n"
            f"{proc.stdout[-8000:]}\n"
            f"---------- stderr (últimas 4000 líneas) ----------\n"
            f"{proc.stderr[-4000:]}"
        )
