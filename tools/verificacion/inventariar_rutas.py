# -*- coding: utf-8 -*-
"""Inventario real de rutas: contrasta el esquema OpenAPI desplegado con la
lista de 36 rutas del README V1.001 (el README dice "38"), y verifica que no
haya enlaces internos rotos en las paginas principales.

Salida:
  * rutas registradas en el despliegue (codigo de ruta, no solo el path)
  * de la lista del README, cuales existen y cuales no (con su ruta real
    equivalente cuando la documentada esta desactualizada)
  * enlaces internos, anclas e identificadores auditados en las 17 paginas
    principales, con la sesion del administrador

Requiere las variables de entorno BITACORA_ADMIN_USER y
BITACORA_ADMIN_PASSWORD. Si falta alguna, termina con codigo 2 sin
realizar la verificacion.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://bitacora-grmv2-production.up.railway.app"

# Lista del README V1.001 (36 rutas: el README dice "38", la lista tiene 36).
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

# Ruta real equivalente cuando la documentada no existe. Se comprueba contra
# el esquema y, si hace falta, contra la respuesta HTTP real.
EQUIVALENTES = {
    "/login": "/auth/login",
    "/registro": "/auth/registro",
    "/referencias": "/api/v1/referencias/tipos",
    "/roles": "/roles-funciones",
    "/calendario": "/vistas/calendario",
    "/timeline": "/vistas/timeline",
    "/metricas": "/api/v1/metricas/resumen",
    "/dependencias": "/api/v1/dependencias/ticket-batch",
}

# Rutas que no aparecen en el esquema OpenAPI pero sí funcionan: las sirve
# FastAPI fuera del router (documentacion interactiva y esquema).
FUERA_DEL_ESQUEMA_PERO_VALIDAS = ("/docs", "/openapi.json")

PATRON_ENLACE = re.compile(r'(?:href|src|action)\s*=\s*["\']([^"\'>]+)["\']')
PATRON_ID = re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']')


def _credenciales_admin():
    usuario = os.environ.get("BITACORA_ADMIN_USER")
    password = os.environ.get("BITACORA_ADMIN_PASSWORD")
    faltantes = []
    if not usuario:
        faltantes.append("BITACORA_ADMIN_USER")
    if not password:
        faltantes.append("BITACORA_ADMIN_PASSWORD")
    if faltantes:
        print(
            "NO VERIFICABLE: faltan las variables de entorno obligatorias: %s"
            % ", ".join(faltantes)
        )
        return None
    return usuario, password


def _redirige_a_login(respuesta) -> bool:
    ubicacion = respuesta.headers.get("location", "")
    return urlparse(ubicacion).path.rstrip("/") == "/auth/login"


def main() -> int:
    credenciales = _credenciales_admin()
    if credenciales is None:
        return 2
    usuario_admin, password_admin = credenciales

    with httpx.Client(base_url=BASE, timeout=30, follow_redirects=False) as c:
        # --- 0) Sesion de administrador -----------------------------------
        r = c.post("/api/v1/auth/login",
                   json={"username": usuario_admin, "password": password_admin})
        print("LOGIN del administrador -> %s" % r.status_code)
        if r.status_code != 200:
            print("No se pudo autenticar la sesion de administrador.")
            return 1
        if not c.cookies.get("access_token"):
            print("El login no devolvio la cookie de sesion access_token.")
            return 1

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
        # OpenAPI publica las API con el prefijo /api/v1; el contraste
        # acepta tanto el path documentado como su equivalente prefijado.
        print("")
        print("=" * 78)
        print(" CONTRASTE CON LAS 36 RUTAS DE LA LISTA DEL README V1.001")
        print(" (el README dice '38 rutas': la lista tiene 36 - ver ERRATA)")
        print("=" * 78)
        existen, faltan = [], []
        for ruta in RUTAS_V1001:
            limpio = ruta.split("?")[0]
            if limpio in registrados:
                existen.append(ruta)
                continue
            if "/api/v1" + limpio in registrados:
                existen.append(ruta)
                continue
            # /docs y /openapi.json los sirve FastAPI fuera del router: no
            # aparecen en el esquema, pero responden.
            if limpio in FUERA_DEL_ESQUEMA_PERO_VALIDAS:
                rr = c.get(limpio)
                if rr.status_code == 200:
                    existen.append(ruta)
                    continue
            faltan.append(ruta)
        print("  existen: %d" % len(existen))
        print("  NO existen como ruta GET: %d" % len(faltan))
        for ruta in faltan:
            equivalente = EQUIVALENTES.get(ruta)
            if equivalente:
                rr = c.get(equivalente)
                print("     - %-28s -> ruta real: %-42s (%s)" % (
                    ruta, equivalente, rr.status_code))
            else:
                rr = c.get(ruta)
                print("     - %-28s -> sin equivalente en el esquema (%s)" % (
                    ruta, rr.status_code))

        # --- 3) Enlaces, anclas e identificadores de las paginas ----------
        print("")
        print("=" * 78)
        print(" ENLACES INTERNOS EN LAS PAGINAS PRINCIPALES")
        print("=" * 78)
        paginas = ("/kanban", "/dashboard", "/tickets", "/espacios",
                   "/tableros", "/notificaciones", "/catalogos",
                   "/roles-funciones", "/usuarios", "/tickets/nuevo",
                   "/admin/reporte-entregas", "/vistas/tabla",
                   "/vistas/gantt", "/vistas/timeline", "/vistas/panel",
                   "/vistas/planner", "/vistas/calendario")
        rotos = []
        rotos_ancla = []
        redirecciones_login = []
        total = 0
        total_ids = 0
        for pagina in paginas:
            rr = c.get(pagina)
            if 300 <= rr.status_code < 400 and _redirige_a_login(rr):
                redirecciones_login.append(pagina)
                continue
            if rr.status_code != 200:
                print("  %-28s -> %s (no se analizan enlaces)" % (
                    pagina, rr.status_code))
                continue

            html = rr.text
            ids_pagina = set(PATRON_ID.findall(html))
            total_ids += len(ids_pagina)
            encontrados = set(PATRON_ENLACE.findall(html))
            rotos_pagina = []
            anclas_rotas_pagina = []
            for enlace in encontrados:
                if enlace.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                parseado = urlparse(enlace)
                if parseado.scheme in ("http", "https") or parseado.netloc:
                    continue  # externo: fuera del alcance
                destino_url = urlparse(urljoin(BASE + pagina, enlace))
                destino = destino_url.path
                if not destino:
                    continue
                total += 1
                r2 = c.get(destino)
                if r2.status_code in (404, 405, 500):
                    rotos_pagina.append((destino, r2.status_code))
                    rotos.append((pagina, destino, r2.status_code))
                    continue
                fragmento = destino_url.fragment
                if (fragmento and r2.status_code == 200 and
                        "html" in r2.headers.get("content-type", "").lower()):
                    ids_destino = set(PATRON_ID.findall(r2.text))
                    if fragmento not in ids_destino:
                        anclas_rotas_pagina.append((destino, fragmento))
                        rotos_ancla.append((pagina, destino, fragmento))

            print("  %-28s -> %s | enlaces internos=%d | ids=%d | rotos=%d | anclas rotas=%d"
                  % (pagina, rr.status_code, len(encontrados), len(ids_pagina),
                     len(rotos_pagina), len(anclas_rotas_pagina)))
            for destino, code in rotos_pagina[:5]:
                print("        ROTO %s -> %s" % (destino, code))

        if redirecciones_login:
            print("  HALLAZGO AGREGADO: SIN SESIÓN / redirección a login en %d "
                  "página(s): %s" % (len(redirecciones_login),
                                      ", ".join(redirecciones_login)))

        print("")
        print("  total de enlaces internos comprobados: %d" % total)
        print("  identificadores HTML revisados: %d" % total_ids)
        print("  enlaces internos rotos: %d" % len(rotos))
        print("  anclas internas rotas: %d" % len(rotos_ancla))
        print("  hallazgos agregados de redireccion a login: %d"
              % (1 if redirecciones_login else 0))
        for origen, destino, code in rotos[:20]:
            print("     %-24s -> %-50s %s" % (origen, destino, code))
        for origen, destino, fragmento in rotos_ancla[:20]:
            print("     %-24s -> %-50s ancla #%s" % (
                origen, destino, fragmento))

        if rotos or rotos_ancla or redirecciones_login:
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
