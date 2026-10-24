# -*- coding: utf-8 -*-
"""Inventario real de rutas: contrasta el esquema OpenAPI desplegado con la
lista de 38 rutas del README V1.001, y verifica que no haya enlaces internos
rotos en las paginas principal.

Salida:
  * rutas registradas en el despliegue (codigo de ruta, no solo el path)
  * de la lista de 38, cuales existen y cuales no (con el motivo)
  * enlaces internos rotos detectados en /kanban, /dashboard y /tickets
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urljoin, urlparse

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://bitacora-grmv2-production.up.railway.app"

# Lista del README V1.001 (38 rutas)
RUTAS_V1001 = [
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

PATRON_ENLACE = re.compile(r'(?:href|src|action)\s*=\s*["\']([^"\'>]+)["\']')


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=30, follow_redirects=True) as c:
        # --- 1) Esquema OpenAPI -------------------------------------------
        r = c.get("/openapi.json")
        if r.status_code != 200:
            print("No se pudo leer /openapi.json (%s)" % r.status_code)
            return 1
        esquema = r.json()
        registrados = sorted(esquema.get("paths", {}).keys())
        print("=" * 78)
        print(" RUTAS REGISTRADAS EN EL DESPLIEGUE: %d" % len(registrados))
        print("=" * 78)
        for ruta in registrados:
            metodos = ",".join(sorted(esquema["paths"][ruta].keys()))
            print("  %-58s [%s]" % (ruta, metodos))

        # --- 2) Contraste con la lista de V1.001 --------------------------
        # El path de OpenAPI no lleva el prefijo /api/v1: se normaliza.
        base_path = ""
        if "paths" in esquema and esquema["paths"]:
            prefijos = {p.split("/")[1] for p in esquema["paths"] if p.startswith("/")}
        else:
            prefijos = set()

        print("")
        print("=" * 78)
        print(" CONTRASTE CON LAS 38 RUTAS DEL README V1.001")
        print("=" * 78)
        existen, faltan = [], []
        for ruta in RUTAS_V1001:
            limpio = ruta.split("?")[0]
            # Se aceptan tanto el path tal cual como con prefijo /api/v1.
            if limpio in registrados:
                existen.append(ruta)
                continue
            if "/api/v1" + limpio in registrados:
                existen.append(ruta)
                continue
            faltan.append(ruta)
        print("  existen: %d" % len(existen))
        print("  NO existen como ruta GET: %d" % len(faltan))
        for ruta in faltan:
            print("     - %s" % ruta)

        # --- 3) Enlaces internos en las paginas ---------------------------
        print("")
        print("=" * 78)
        print(" ENLACES INTERNOS EN LAS PAGINAS PRINCIPALES")
        print("=" * 78)
        rotos = []
        total = 0
        for pagina in ("/kanban", "/dashboard", "/tickets", "/espacios",
                       "/tableros", "/notificaciones", "/catalogos",
                       "/admin/reporte-entregas", "/vistas/tabla",
                       "/vistas/gantt", "/vistas/timeline", "/vistas/panel",
                       "/vistas/planner"):
            rr = c.get(pagina)
            if rr.status_code != 200:
                print("  %-28s -> %s (no se analizan enlaces)" % (pagina, rr.status_code))
                continue
            html = rr.text
            encontrados = set(PATRON_ENLACE.findall(html))
            rotos_pagina = []
            for enlace in encontrados:
                if enlace.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                parseado = urlparse(enlace)
                if parseado.scheme in ("http", "https"):
                    continue  # externo: fuera del alcance
                destino = parseado.path or "/"
                if not destino.startswith("/"):
                    destino = urljoin(BASE + pagina, destino)
                destino = destino.split("?")[0].split("#")[0]
                if not destino:
                    continue
                total += 1
                r2 = c.get(destino)
                if r2.status_code in (404, 405, 500):
                    rotos_pagina.append((destino, r2.status_code))
                    rotos.append((pagina, destino, r2.status_code))
            print("  %-28s -> %s | enlaces internos=%d | rotos=%d"
                  % (pagina, rr.status_code, len(encontrados), len(rotos_pagina)))
            for destino, code in rotos_pagina[:5]:
                print("        ROTO %s -> %s" % (destino, code))

        print("")
        print("  total de enlaces internos comprobados: %d" % total)
        print("  enlaces internos rotos: %d" % len(rotos))
        for origen, destino, code in rotos[:20]:
            print("     %-24s -> %-50s %s" % (origen, destino, code))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
