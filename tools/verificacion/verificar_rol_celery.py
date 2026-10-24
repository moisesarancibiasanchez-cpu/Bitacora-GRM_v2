#!/usr/bin/env python
"""Verifica el arranque de los tres roles de Bitácora GRM (web/worker/beat).

Cubre dos defectos reales encontrados al desplegar en Railway:

1. ``start.sh`` resolvia el rol con ``$RAILWAY_SERVICE_ROLE``. Railway NO
   inyecta esa variable (la lista oficial de variables es exhaustiva y no la
   incluye), de modo que TODOS los servicios caian en el rol "web" y
   arrancaban gunicorn en vez de celery: el servicio quedaba "activo" sin
   consumir ninguna tarea. Ahora el rol se resuelve por
   ``$PROC_TYPE`` > ``$APP_ROLE`` > ``$RAILWAY_SERVICE_ROLE`` >
   ``$RAILWAY_SERVICE_NAME`` (esta ultima SI la inyecta Railway).

2. ``CELERY_BROKER_URL`` / ``CELERY_RESULT_BACKEND`` tenian default local
   (``redis://localhost:6379/1`` y ``/2``) y no se derivaban de
   ``REDIS_URL`` (la unica variable que Railway inyecta al adjuntar el
   plugin de Redis). Un worker/beat recien creado publicaba contra
   localhost y fallaba al encolar.

El script NO usa mocks de la logica: ejecuta el ``start.sh`` real con
ejecutables "stub" que sustituyen a gunicorn/celery para poder observar QUE
proceso se lanzaria, sin dejar gunicorn ni celery reales en marcha.

Salida: 0 si todas las comprobaciones pasan, 1 si alguna falla.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
START_SH = RAIZ / "start.sh"
BASH = r"C:\Program Files\Git\bin\bash.exe"

FALLOS: list[str] = []
PASADOS = 0


def _ruta_corta(ruta: str) -> str:
    """Devuelve la ruta en formato 8.3 (sin acentos) para Git Bash.

    El perfil de Windows del usuario contiene una 'é', que Git Bash maneja
    de forma fiable en formato POSIX UTF-8 pero no cuando el path llega
    desde la API de Windows. GetShortPathNameW lo resuelve.
    """
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        longitud = ctypes.windll.kernel32.GetShortPathNameW(ruta, buffer, 1024)
        if longitud and longitud < 1024:
            return buffer.value
    except Exception:  # pragma: no cover - solo en Windows
        pass
    return ruta


def _a_posix(ruta: str) -> str:
    """Convierte una ruta de Windows en ruta POSIX para Git Bash."""
    ruta = _ruta_corta(ruta)
    if len(ruta) > 2 and ruta[1] == ":":
        return "/" + ruta[0].lower() + ruta[2:].replace("\\", "/")
    return ruta.replace("\\", "/")


def comprobar(condicion: bool, descripcion: str, detalle: str = "") -> None:
    global PASADOS
    if condicion:
        PASADOS += 1
        print(f"  [OK]   {descripcion}")
    else:
        FALLOS.append(descripcion)
        print(f"  [FALLA] {descripcion}")
        if detalle:
            for linea in detalle.strip().splitlines()[-12:]:
                print(f"          | {linea}")


# ----------------------------------------------------------------------
# Parte 1: derivacion de las URLs de Celery desde REDIS_URL
# ----------------------------------------------------------------------
def _settings(**entorno):
    """Instancia Settings con un entorno controlado (sin .env del repo)."""
    for clave in (
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ):
        os.environ.pop(clave, None)
    os.environ.update({k: v for k, v in entorno.items() if v is not None})
    sys.path.insert(0, str(RAIZ))
    try:
        from app.core.config import Settings

        return Settings(_env_file=None)
    finally:
        for clave in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
            os.environ.pop(clave, None)


def verificar_configuracion() -> None:
    print("\n[1] Derivacion de CELERY_BROKER_URL / CELERY_RESULT_BACKEND")
    print("-" * 72)

    s = _settings(REDIS_URL="redis://default:clave@host.railway.internal:6379")
    comprobar(
        s.CELERY_BROKER_URL == "redis://default:clave@host.railway.internal:6379/1",
        "broker derivado de REDIS_URL (base 1) conservando credenciales",
        f"obtenido: {s.CELERY_BROKER_URL}",
    )
    comprobar(
        s.CELERY_RESULT_BACKEND == "redis://default:clave@host.railway.internal:6379/2",
        "backend derivado de REDIS_URL (base 2)",
        f"obtenido: {s.CELERY_RESULT_BACKEND}",
    )

    s = _settings(REDIS_URL="redis://h:6379/0")
    comprobar(
        s.CELERY_BROKER_URL == "redis://h:6379/1",
        "base existente en REDIS_URL sustituida por la del broker",
        f"obtenido: {s.CELERY_BROKER_URL}",
    )

    s = _settings(
        REDIS_URL="redis://h:6379",
        CELERY_BROKER_URL="redis://explicito:6379/7",
    )
    comprobar(
        s.CELERY_BROKER_URL == "redis://explicito:6379/7",
        "CELERY_BROKER_URL explicito en el entorno NO se sobrescribe",
        f"obtenido: {s.CELERY_BROKER_URL}",
    )
    comprobar(
        s.CELERY_RESULT_BACKEND == "redis://h:6379/2",
        "el backend si se deriva aunque el broker sea explicito",
        f"obtenido: {s.CELERY_RESULT_BACKEND}",
    )

    s = _settings()
    comprobar(
        s.CELERY_BROKER_URL == "redis://localhost:6379/1"
        and s.CELERY_RESULT_BACKEND == "redis://localhost:6379/2",
        "sin REDIS_URL se conservan los defaults de desarrollo",
        f"obtenido: {s.CELERY_BROKER_URL} / {s.CELERY_RESULT_BACKEND}",
    )


# ----------------------------------------------------------------------
# Parte 2: resolucion de rol ejecutando el start.sh real
# ----------------------------------------------------------------------
STUB = "#!/usr/bin/env bash\nprintf 'STUB_PROCESO=%s\\n' \"$(basename \"$0\")\"\nprintf 'STUB_ARGS=%s\\n' \"$*\"\nexit 0\n"


def _crear_stubs(destino: Path) -> Path:
    """Crea ejecutables stub para gunicorn y celery (sin ejecutar los reales)."""
    stub_dir = destino / "stub"
    stub_dir.mkdir(parents=True, exist_ok=True)
    for nombre in ("gunicorn", "celery"):
        ruta = stub_dir / nombre
        ruta.write_text(STUB, encoding="utf-8", newline="\n")
    return stub_dir


def _ejecutar_start_sh(
    trabajo: Path, entorno_extra: dict[str, str]
) -> tuple[int, str]:
    """Ejecuta el start.sh real (copia con LF) y devuelve (rc, salida)."""
    # Copia con finales de linea LF: el working tree de Windows puede tener
    # CRLF (core.autocrlf=true) y bash no lo tolera. En Railway el blob
    # llega con LF (verificado: CR=0).
    guion = trabajo / "start.sh"
    texto = START_SH.read_text(encoding="utf-8")
    guion.write_text(texto, encoding="utf-8", newline="\n")
    guion.chmod(0o755)

    stub_dir = trabajo / "stub"
    entorno = os.environ.copy()
    entorno.update(
        {
            "PATH": _a_posix(str(stub_dir))
            + ":"
            + entorno.get("PATH", ""),
            "SECRET_KEY": "a" * 64,
            "DATABASE_URL": "",
            "AUTO_INIT_DB": "false",
            "SEED_DATA": "false",
        }
    )
    for clave in ("PROC_TYPE", "APP_ROLE", "RAILWAY_SERVICE_ROLE", "RAILWAY_SERVICE_NAME"):
        entorno.pop(clave, None)
    entorno.update(entorno_extra)

    proc = subprocess.run(
        [BASH, "-c", f"cd '{_a_posix(str(trabajo))}' && bash ./start.sh"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=entorno,
        timeout=120,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def verificar_roles() -> None:
    print("\n[2] Resolucion de rol ejecutando el start.sh real")
    print("-" * 72)

    with tempfile.TemporaryDirectory(prefix="grm_rol_") as tmp:
        trabajo = Path(tmp)
        _crear_stubs(trabajo)

        # Escenario A: servicio web (nombre real del servicio en produccion).
        rc, salida = _ejecutar_start_sh(trabajo, {"RAILWAY_SERVICE_NAME": "Bitacora-GRM_v2"})
        comprobar(
            rc == 0 and "STUB_PROCESO=gunicorn" in salida,
            "nombre del servicio web -> arranca gunicorn",
            salida,
        )

        # Escenario B: PROC_TYPE=worker.
        rc, salida = _ejecutar_start_sh(trabajo, {"PROC_TYPE": "worker"})
        comprobar(
            rc == 0 and "STUB_PROCESO=celery" in salida and " worker " in salida,
            "PROC_TYPE=worker -> arranca celery worker",
            salida,
        )

        # Escenario C: PROC_TYPE=beat.
        rc, salida = _ejecutar_start_sh(trabajo, {"PROC_TYPE": "beat"})
        comprobar(
            rc == 0 and "STUB_PROCESO=celery" in salida and " beat " in salida,
            "PROC_TYPE=beat -> arranca celery beat",
            salida,
        )
        comprobar(
            "--schedule=" in salida,
            "celery beat recibe un fichero de calendario escribible",
            salida,
        )

        # Escenario D: APP_ROLE (alias de PROC_TYPE).
        rc, salida = _ejecutar_start_sh(trabajo, {"APP_ROLE": "worker"})
        comprobar(
            rc == 0 and "STUB_PROCESO=celery" in salida and " worker " in salida,
            "APP_ROLE=worker -> arranca celery worker",
            salida,
        )

        # Escenario E: solo el nombre del servicio (Railway siempre lo da).
        rc, salida = _ejecutar_start_sh(trabajo, {"RAILWAY_SERVICE_NAME": "celery-worker"})
        comprobar(
            rc == 0 and "STUB_PROCESO=celery" in salida and " worker " in salida,
            "RAILWAY_SERVICE_NAME=celery-worker -> celery worker (sin variables extra)",
            salida,
        )

        rc, salida = _ejecutar_start_sh(trabajo, {"RAILWAY_SERVICE_NAME": "celery-beat"})
        comprobar(
            rc == 0 and "STUB_PROCESO=celery" in salida and " beat " in salida,
            "RAILWAY_SERVICE_NAME=celery-beat -> celery beat (sin variables extra)",
            salida,
        )

        # Escenario F: compatibilidad con $RAILWAY_SERVICE_ROLE (Heroku).
        rc, salida = _ejecutar_start_sh(
            trabajo, {"RAILWAY_SERVICE_ROLE": "worker"}
        )
        comprobar(
            rc == 0 and "STUB_PROCESO=celery" in salida and " worker " in salida,
            "RAILWAY_SERVICE_ROLE=worker -> celery worker (compatibilidad)",
            salida,
        )

        # Escenario G: rol explicito invalido -> debe abortar, no arrancar web.
        rc, salida = _ejecutar_start_sh(trabajo, {"PROC_TYPE": "inventado"})
        comprobar(
            rc != 0 and "STUB_PROCESO" not in salida and "rol desconocido" in salida.lower(),
            "PROC_TYPE invalido -> aborta con codigo de error (no arranca gunicorn)",
            salida,
        )

        # Escenario H: 'cron' NO debe mapearse a beat (el cron de Railway
        # exige que el proceso termine; celery beat no termina).
        rc, salida = _ejecutar_start_sh(trabajo, {"PROC_TYPE": "cron"})
        comprobar(
            rc != 0 and "STUB_PROCESO" not in salida,
            "PROC_TYPE=cron -> aborta (celery beat no sirve como Cron Job de Railway)",
            salida,
        )


def main() -> int:
    print("=" * 72)
    print("VERIFICACION: roles web/worker/beat de Bitacora GRM en Railway")
    print("=" * 72)
    print(f"Repo: {RAIZ}")
    if not BASH or not Path(BASH).exists():
        print(f"ERROR: no se encuentra Git Bash en {BASH}")
        return 1
    if not START_SH.exists():
        print(f"ERROR: no existe {START_SH}")
        return 1

    verificar_configuracion()
    verificar_roles()

    print()
    print("=" * 72)
    total = PASADOS + len(FALLOS)
    if FALLOS:
        print(f"RESULTADO: {PASADOS}/{total} comprobaciones OK, {len(FALLOS)} FALLAN")
        for fallo in FALLOS:
            print(f"  - {fallo}")
        return 1
    print(f"RESULTADO: {PASADOS}/{total} comprobaciones OK, 0 fallos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
