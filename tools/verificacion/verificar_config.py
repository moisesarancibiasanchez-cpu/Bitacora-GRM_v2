# -*- coding: utf-8 -*-
"""Verificacion REAL de app/core/config.py con procesos limpios.

Cada escenario se ejecuta en un subproceso con su propio entorno, porque
``Settings`` es un singleton (``@lru_cache``) y ``_exportar_a_environ``
contamina ``os.environ`` con los valores por defecto.

Escenarios
----------
1. Railway sin PUBLIC_BASE_URL explicita  -> se DERIVA de RAILWAY_PUBLIC_DOMAIN.
2. PUBLIC_BASE_URL explicita en https     -> se respeta tal cual.
3. PUBLIC_BASE_URL explicita en http      -> NO se toca (el guard avisa/aborta).
4. Sin variables de Railway               -> se mantiene el default.
5. Produccion + CORS '*'                  -> arranca (aviso, no bloqueante).
6. Produccion + SECRET_KEY vacia          -> aviso bloqueante (se mantiene).
7. Desarrollo + CORS '*' explicito        -> RuntimeError (comodin en dev).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def _correr(nombre_escenario, entorno_extra, quitar=()):
    env = dict(os.environ)
    for clave in ("DEBUG", "PUBLIC_BASE_URL", "CORS_ORIGINS", "SECRET_KEY",
                  "RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "DATABASE_URL",
                  "USE_SQLITE", "POSTGRES_USER", "POSTGRES_PASSWORD",
                  "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_PORT"):
        env.pop(clave, None)
    env["PYTHONPATH"] = RAIZ
    env["PYTHONIOENCODING"] = "utf-8"
    for clave in quitar:
        env.pop(clave, None)
    env.update(entorno_extra)
    proc = subprocess.run(
        [PY, "-X", "utf8", os.path.join(RAIZ, "tools", "verificacion", "_probe_config.py")],
        cwd=RAIZ, env=env, capture_output=True, text=True, encoding="utf-8",
        timeout=120,
    )
    salida = proc.stdout or ""
    datos = None
    for linea in salida.splitlines():
        if linea.startswith("@@JSON@@"):
            datos = json.loads(linea[len("@@JSON@@"):])
    if datos is None:
        print("[debug] %s stdout=%r stderr=%r" % (nombre_escenario, salida[-600:], (proc.stderr or "")[-600:]))
    return datos, salida, proc.stderr or ""


def main() -> int:
    # --- 1) Railway sin PUBLIC_BASE_URL explicita ------------------------
    d, _, _ = _correr(
        "railway-derivado",
        {
            "DEBUG": "false",
            "SECRET_KEY": "x" * 64,
            "CORS_ORIGINS": '["https://bitacora-grmv2-production.up.railway.app"]',
            "RAILWAY_PUBLIC_DOMAIN": "bitacora-grmv2-production.up.railway.app",
        },
    )
    if d and "error" not in d:
        _check(
            "1) PUBLIC_BASE_URL derivado de RAILWAY_PUBLIC_DOMAIN",
            d["PUBLIC_BASE_URL"] == "https://bitacora-grmv2-production.up.railway.app",
            "PUBLIC_BASE_URL=%r" % d["PUBLIC_BASE_URL"],
        )
        _check(
            "1) con la derivacion NO queda ningun aviso bloqueante",
            d["avisos"] == [],
            "avisos=%r" % d["avisos"],
        )
    else:
        _check("1) PUBLIC_BASE_URL derivado de RAILWAY_PUBLIC_DOMAIN", False, repr(d))

    # --- 1b) RAILWAY_STATIC_URL como alternativa -------------------------
    d, _, _ = _correr(
        "railway-static-url",
        {
            "DEBUG": "false",
            "SECRET_KEY": "y" * 64,
            "CORS_ORIGINS": '["https://bitacora-grmv2-production.up.railway.app"]',
            "RAILWAY_STATIC_URL": "https://static.example.up.railway.app/",
        },
    )
    if d and "error" not in d:
        _check(
            "1b) PUBLIC_BASE_URL derivado de RAILWAY_STATIC_URL (sin barra final)",
            d["PUBLIC_BASE_URL"] == "https://static.example.up.railway.app",
            "PUBLIC_BASE_URL=%r" % d["PUBLIC_BASE_URL"],
        )
    else:
        _check("1b) PUBLIC_BASE_URL derivado de RAILWAY_STATIC_URL", False, repr(d))

    # --- 2) PUBLIC_BASE_URL explicita en https ---------------------------
    d, _, _ = _correr(
        "puburl-https",
        {
            "DEBUG": "false",
            "SECRET_KEY": "z" * 64,
            "CORS_ORIGINS": '["https://mi-dominio.example"]',
            "PUBLIC_BASE_URL": "https://mi-dominio.example",
            "RAILWAY_PUBLIC_DOMAIN": "otro.up.railway.app",
        },
    )
    if d and "error" not in d:
        _check(
            "2) PUBLIC_BASE_URL explicita en https se respeta (no se sobrescribe)",
            d["PUBLIC_BASE_URL"] == "https://mi-dominio.example",
            "PUBLIC_BASE_URL=%r" % d["PUBLIC_BASE_URL"],
        )
    else:
        _check("2) PUBLIC_BASE_URL explicita en https se respeta", False, repr(d))

    # --- 3) PUBLIC_BASE_URL explicita en http ---------------------------
    d, _, _ = _correr(
        "puburl-http",
        {
            "DEBUG": "false",
            "SECRET_KEY": "w" * 64,
            "CORS_ORIGINS": '["https://mi-dominio.example"]',
            "PUBLIC_BASE_URL": "http://mi-dominio.example",
        },
    )
    if d and "error" not in d:
        _check(
            "3) PUBLIC_BASE_URL explicita en http NO se toca (el guard sigue avisando)",
            d["PUBLIC_BASE_URL"] == "http://mi-dominio.example",
            "PUBLIC_BASE_URL=%r" % d["PUBLIC_BASE_URL"],
        )
        _check(
            "3) y el aviso de HTTPS sigue presente (guard no debilitado)",
            any("HTTPS" in a for a in d["avisos"]),
            "avisos=%r" % d["avisos"],
        )
    else:
        _check("3) PUBLIC_BASE_URL explicita en http NO se toca", False, repr(d))

    # --- 4) Sin variables de Railway ------------------------------------
    d, _, _ = _correr(
        "sin-railway",
        {"DEBUG": "true", "SECRET_KEY": "d" * 64},
    )
    if d and "error" not in d:
        _check(
            "4) sin variables de Railway se mantiene el default",
            d["PUBLIC_BASE_URL"] == "http://localhost:8000",
            "PUBLIC_BASE_URL=%r" % d["PUBLIC_BASE_URL"],
        )
    else:
        _check("4) sin variables de Railway se mantiene el default", False, repr(d))

    # --- 5) Produccion + CORS comodin -----------------------------------
    d, salida, _ = _correr(
        "cors-comodin",
        {
            "DEBUG": "false",
            "SECRET_KEY": "c" * 64,
            "CORS_ORIGINS": '["*"]',
            "RAILWAY_PUBLIC_DOMAIN": "bitacora-grmv2-production.up.railway.app",
        },
    )
    if d and "error" not in d:
        _check(
            "5) produccion + CORS '*' ARRANCA (sin avisos bloqueantes)",
            d["avisos"] == [],
            "avisos=%r" % d["avisos"],
        )
    else:
        _check("5) produccion + CORS '*' ARRANCA", False, repr(d))

    # --- 6) Produccion + SECRET_KEY vacia -------------------------------
    d, _, _ = _correr(
        "sin-secret-key",
        {
            "DEBUG": "false",
            "SECRET_KEY": "",
            "CORS_ORIGINS": '["https://mi-dominio.example"]',
            "PUBLIC_BASE_URL": "https://mi-dominio.example",
        },
    )
    if d and "error" not in d:
        _check(
            "6) SECRET_KEY vacia sigue siendo AVISO BLOQUEANTE",
            any("SECRET_KEY" in a for a in d["avisos"]),
            "avisos=%r" % d["avisos"],
        )
    else:
        _check("6) SECRET_KEY vacia sigue siendo AVISO BLOQUEANTE", False, repr(d))

    # --- 7) Desarrollo + CORS comodin explicito -------------------------
    d, _, _ = _correr(
        "dev-comodin",
        {
            "DEBUG": "true",
            "SECRET_KEY": "e" * 64,
            "CORS_ORIGINS": '["*"]',
        },
    )
    if d and "error" in d:
        _check(
            "7) desarrollo + CORS '*' explicito -> RuntimeError",
            d["error"] == "RuntimeError",
            "%s: %s" % (d["error"], d["mensaje"][:120]),
        )
    else:
        _check("7) desarrollo + CORS '*' explicito -> RuntimeError", False, repr(d))

    # --- 8) Desarrollo sin CORS explicito (default de la clase) ---------
    d, _, _ = _correr(
        "dev-default",
        {"DEBUG": "true", "SECRET_KEY": "f" * 64},
    )
    if d and "error" not in d:
        _check(
            "8) desarrollo sin CORS explicito NO aborta",
            d["avisos"] == [],
            "avisos=%r" % d["avisos"],
        )
    else:
        _check("8) desarrollo sin CORS explicito NO aborta", False, repr(d))

    print("")
    if FALLOS:
        print("RESULTADO CONFIG: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO CONFIG: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
