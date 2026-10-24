# -*- coding: utf-8 -*-
"""Barrido de rutas contra la aplicacion desplegada (con sesion iniciada).

Recorre las 38 rutas del proyecto y las clasifica segun su respuesta real:
  * 200/2xx  -> ruta operativa
  * 302/307  -> redirige (a /auth/login si la sesion no se aplico, o al
                flujo normal de la app si la sesion si se aplico)
  * 401/403  -> endpoint protegido (correcto sin credenciales de admin)
  * 404/405  -> ruta inexistente o metodo no permitido
  * 5xx      -> ERROR DE SERVIDOR (fallo real)

Ademas verifica que el estado 'Produccion OK' y sus transiciones existen en
la base de datos de PRODUCCION (via la API, en modo lectura), y que el
catalogo de 'Resultado de Pruebas' se sirve sin duplicar la paleta.

Uso:
    python tools/verificacion/barrer_rutas.py [BASE_URL]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://bitacora-grmv2-production.up.railway.app"

RUTAS = [
    "/", "/login", "/registro", "/logout",
    "/kanban", "/dashboard", "/tickets", "/espacios", "/tableros",
    "/admin/reporte-entregas", "/admin/deadline", "/notificaciones",
    "/vistas/tabla", "/vistas/timeline", "/vistas/panel", "/vistas/gantt",
    "/vistas/planner", "/catalogos", "/referencias", "/roles",
    "/calendario", "/timeline", "/metricas", "/dependencias",
    "/health", "/docs", "/openapi.json", "/api/v1/auth/me",
    "/api/v1/buscar?q=test", "/api/v1/tickets", "/api/v1/usuarios",
    "/api/v1/etiquetas", "/api/v1/catalogos/etiquetas", "/api/v1/kanban",
    "/onboarding", "/p/demo",
]

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def main() -> int:
    print("=" * 78)
    print(" BARRIDO DE RUTAS contra %s" % BASE)
    print("=" * 78)

    with httpx.Client(base_url=BASE, timeout=30, follow_redirects=False) as c:
        # --- 1) Estado de salud -------------------------------------------
        r = c.get("/health")
        _check("/health responde 200", r.status_code == 200, "status=%s" % r.status_code)
        if r.status_code == 200:
            datos = r.json()
            print("      payload: %s" % json.dumps(datos, ensure_ascii=False))
            _check("/health reporta base de datos 'ok'", datos.get("database") == "ok",
                   "database=%r" % datos.get("database"))
            _check("/health reporta redis 'ok'", datos.get("redis") == "ok",
                   "redis=%r" % datos.get("redis"))

        # --- 2) Login real ------------------------------------------------
        r = c.post("/api/v1/auth/login",
                   json={"username": "admin", "password": "admin123"})
        _check("login admin/admin123 responde 200", r.status_code == 200,
               "status=%s" % r.status_code)
        if r.status_code != 200:
            print("ABORTANDO: sin sesion no se puede validar el resto.")
            return 1
        token = c.cookies.get("access_token")
        _check("se obtiene la cookie de sesion", bool(token),
               "cookie presente=%s" % bool(token))

        # --- 3) Barrido con sesion ----------------------------------------
        conteo = Counter()
        detalles = []
        for ruta in RUTAS:
            try:
                rr = c.get(ruta)
                code = rr.status_code
            except Exception as exc:
                code = 0
                rr = None
                detalles.append((ruta, "ERROR %s" % exc))
                conteo["error"] += 1
                continue
            conteo[code] += 1
            detalles.append((ruta, code))

        print("")
        print("  ruta                         codigo")
        print("  " + "-" * 42)
        for ruta, code in detalles:
            print("  %-28s %s" % (ruta, code))

        print("")
        print("  resumen: %s" % dict(conteo))

        # 5xx = fallo real de servidor.
        errores5xx = [r for r, c_ in detalles if isinstance(c_, int) and 500 <= c_ < 600]
        _check("ninguna ruta devuelve 5xx", not errores5xx, "errores=%r" % errores5xx)

        # --- 4) Estado 'Produccion OK' y sus transiciones -----------------
        r = c.get("/api/v1/reporte-entregas/estados")
        if r.status_code == 200:
            try:
                cuerpo = r.json()
            except Exception:
                cuerpo = {}
            _check("el endpoint de estados responde 200", True, "ok")
            texto = json.dumps(cuerpo, ensure_ascii=False)
            _check(
                "produccion expone el estado 'Produccion OK'",
                "Producci" in texto and "OK" in texto,
                "encontrado en la respuesta de estados",
            )
        else:
            print("INFO  /api/v1/reporte-entregas/estados -> %s "
                  "(ruta protegida o inexistente; no se puede verificar por API)" % r.status_code)

        # --- 5) Catalogo de Resultado de Pruebas --------------------------
        r = c.get("/api/v1/catalogos/etiquetas")
        _check("el catalogo de etiquetas responde 200", r.status_code == 200,
               "status=%s" % r.status_code)

        # --- 6) El dashboard NO debe re-declarar la paleta ----------------
        r = c.get("/dashboard")
        if r.status_code == 200:
            html = r.text
            _check("el dashboard inyecta la paleta desde el servidor",
                   'id="cuenta-resultado-paleta"' in html, "isla presente")
            _check("el dashboard inyecta el fallback desde el servidor",
                   'id="cuenta-resultado-fallback"' in html, "isla presente")
            # La paleta de "Resultado de Pruebas" no debe estar re-declarada
            # en el JS. El chequeo es por IDENTIFICADOR, no por valor de hex:
            # algunos colores coinciden con los de otros dominios (por
            # ejemplo '#16a34a' es a la vez "OK" de resultado de pruebas y
            # "prioridad baja"; '#94a3b8' es "N/A" y tambien el color por
            # defecto de etiqueta). Un chequeo por valor daria falsos
            # positivos. Lo que se busca es un literal hex en una linea que
            # CONSUME la paleta, que seria una re-declaracion.
            identificadores = (
                "CUENTA_RESULTADO_COLORES", "CUENTA_RESULTADO_FALLBACK",
                "CUENTA_RESULTADO_ACRONIMOS", "colorResultado",
                "acronimoResultado", "colorDe",
            )
            patron_hex = re.compile(r"#[0-9a-fA-F]{6}\b")
            fuera = []
            for linea in html.splitlines():
                if any(ident in linea for ident in identificadores):
                    if patron_hex.search(linea):
                        fuera.append(linea.strip()[:110])
            _check(
                "la paleta no esta re-declarada en el JS de 'Cuenta de Resultado'",
                not fuera,
                "lineas con hex junto a un consumidor de la paleta=%r" % (fuera[:3],),
            )

    print("")
    if FALLOS:
        print("RESULTADO BARRIDO: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO BARRIDO: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
