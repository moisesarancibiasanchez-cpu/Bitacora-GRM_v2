# -*- coding: utf-8 -*-
"""Vigila el redeploy de Railway hasta que /health responda 200.

Imprime el estado cada 30 s. Termina con codigo 0 cuando la aplicacion
responde 200 en /health y ademas valida /, /kanban y /dashboard con la
cookie de sesion (login real admin/admin123).
"""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "https://bitacora-grmv2-production.up.railway.app"
TIMEOUT = 25
INTERVALO = 30
MAX_INTENTOS = 24  # 12 minutos


def _estado(ruta):
    try:
        r = httpx.get(BASE + ruta, timeout=TIMEOUT, follow_redirects=False)
        return r.status_code, r.text[:160]
    except Exception as exc:
        return None, str(exc)[:160]


def main() -> int:
    for intento in range(1, MAX_INTENTOS + 1):
        codigo, detalle = _estado("/health")
        marca = "OK " if codigo == 200 else "-- "
        print("[%02d] %s/health -> %s %s" % (intento, marca, codigo, detalle[:120]),
              flush=True)
        if codigo == 200:
            print("")
            print("=== La aplicacion responde 200 en /health ===")
            with httpx.Client(base_url=BASE, timeout=TIMEOUT,
                              follow_redirects=False) as c:
                for ruta in ("/", "/docs", "/kanban", "/dashboard",
                             "/api/v1/buscar?q=test"):
                    s, t = _estado(ruta)
                    print("  %-26s -> %s" % (ruta, s))

                # Login real y acceso a las rutas autenticadas.
                try:
                    r = c.post("/api/v1/auth/login",
                               json={"username": "admin", "password": "admin123"})
                    print("  login admin/admin123    -> %s" % r.status_code)
                    if r.status_code == 200:
                        for ruta in ("/kanban", "/dashboard"):
                            rr = c.get(ruta)
                            cuerpo = rr.text
                            print("  %-26s -> %s | badge=%s | paleta=%s" % (
                                ruta, rr.status_code,
                                "data-resultado-pruebas" in cuerpo,
                                'id="cuenta-resultado-paleta"' in cuerpo,
                            ))
                except Exception as exc:
                    print("  login -> error: %s" % exc)
            return 0
        time.sleep(INTERVALO)

    print("")
    print("=== La aplicacion SIGUE sin responder 200 tras %d intentos ===" % MAX_INTENTOS)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
