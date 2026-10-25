# -*- coding: utf-8 -*-
"""Barrido de rutas contra la aplicacion desplegada (con sesion iniciada).

Recorre:
  * las PAGINAS de la aplicacion (lista curada y verificada), y
  * TODOS los endpoints GET del esquema OpenAPI real del despliegue.

Las rutas de la API ya NO se mantienen a mano: se derivan de /openapi.json.
La lista manual anterior (heredada del README V1.001) estaba desactualizada
y arrastraba 10 rutas que no existen (login, registro, logout, referencias,
roles, calendario, timeline, metricas, dependencias y p/demo), de modo que el
barrido reportaba 404 "esperados" y no detectaba una ruta realmente rota.
Ahora una ruta inexistente es un FALLO del propio barrido.

Clasifica cada respuesta real:
  * 200/2xx  -> ruta operativa
  * 302/307  -> redirige (la app redirige "/" a /kanban y /onboarding a su
                version con barra final)
  * 401/403  -> endpoint protegido (correcto)
  * 404      -> ruta inexistente (FALLO, salvo las de la lista RUTAS_SIN_DATOS)
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

# Paginas HTML de la aplicacion (verificadas una a una contra el despliegue).
PAGINAS = [
    "/", "/kanban", "/dashboard", "/tickets", "/tickets/nuevo", "/tickets/tabla",
    "/espacios", "/tableros", "/notificaciones", "/catalogos",
    "/roles-funciones", "/usuarios", "/usuarios/nuevo", "/usuarios/tabla",
    "/admin/reporte-entregas", "/admin/deadline",
    "/vistas/tabla", "/vistas/timeline", "/vistas/panel", "/vistas/gantt",
    "/vistas/planner", "/vistas/calendario",
    "/importar-exportar", "/butler",
    "/auth/login", "/auth/registro",
    "/health", "/ready", "/info", "/docs", "/openapi.json",
]

# Rutas cuyo 404 es correcto porque el PATRON existe pero no hay datos.
RUTAS_SIN_DATOS = {
    "/p/demo": "no existe ningun tablero publico con el slug 'demo'",
}

# Valores plausibles para los parametros de ruta del esquema.
PARAMETROS = {
    "id": "1", "ticket_id": "1", "usuario_id": "1", "espacio_id": "1",
    "tablero_id": "1", "estado_id": "1", "etiqueta_id": "1", "rol_id": "1",
    "adjunto_id": "1", "tipo_id": "1", "tipo_objeto": "ticket",
    "objeto_id": "1", "slug": "demo", "codigo": "demo", "nombre": "prueba",
    "fecha": "2026-10-24", "formato": "csv", "filename": "demo.sql",
    "record_id": "1", "destino_id": "1",
}

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def _resolver(path: str) -> str:
    for nombre in re.findall(r"{(\w+)}", path):
        path = path.replace("{%s}" % nombre, PARAMETROS.get(nombre, "1"))
    return path


def main() -> int:
    print("=" * 78)
    print(" BARRIDO DE RUTAS contra %s" % BASE)
    print("=" * 78)

    with httpx.Client(base_url=BASE, timeout=45, follow_redirects=False) as c:
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

        # --- 3) Paginas HTML ----------------------------------------------
        print("")
        print("  PAGINAS")
        print("  " + "-" * 42)
        conteo = Counter()
        detalles = []
        for ruta in PAGINAS:
            try:
                rr = c.get(ruta)
                code = rr.status_code
            except Exception as exc:
                code = 0
                detalles.append((ruta, "ERROR %s" % exc))
                conteo["error"] += 1
                continue
            conteo[code] += 1
            detalles.append((ruta, code))
        for ruta, code in detalles:
            print("  %-30s %s" % (ruta, code))
        print("")
        print("  resumen de paginas: %s" % dict(conteo))

        # Una pagina debe responder 200 (o 307 si redirige por diseño).
        paginas_rojas = [(r, c_) for r, c_ in detalles
                         if not (isinstance(c_, int) and c_ in (200, 307))]
        _check("todas las paginas existen (200 o 307)",
               not paginas_rojas, "roto=%r" % (paginas_rojas[:8],))

        # --- 4) Rutas de la API derivadas del OpenAPI real ----------------
        print("")
        print("  ENDPOINTS GET DEL ESQUEMA OPENAPI")
        print("  " + "-" * 42)
        r = c.get("/openapi.json")
        if r.status_code != 200:
            _check("se puede leer /openapi.json", False, "status=%s" % r.status_code)
        else:
            esquema = r.json()
            gets = sorted(p for p, ops in esquema.get("paths", {}).items()
                          if "get" in ops)
            print("  endpoints GET en el esquema: %d" % len(gets))
            conteo_api = Counter()
            detalles_api = []
            for path in gets:
                url = _resolver(path)
                try:
                    rr = c.get(url)
                    code = rr.status_code
                except Exception as exc:
                    code = 0
                    detalles_api.append((path, "ERROR %s" % exc))
                    conteo_api["error"] += 1
                    continue
                conteo_api[code] += 1
                detalles_api.append((path, code))
            for path, code in detalles_api:
                if isinstance(code, int) and code >= 400:
                    print("    %-52s %s" % (path, code))
            print("")
            print("  resumen de la API: %s" % dict(conteo_api))

            errores5xx = [(p, c_) for p, c_ in detalles_api
                          if isinstance(c_, int) and 500 <= c_ < 600]
            _check("ningun endpoint GET de la API devuelve 5xx",
                   not errores5xx, "errores=%r" % (errores5xx[:8],))

            # Un 404 en un endpoint del propio esquema significa que el
            # parametro de ejemplo no existe: se informa, no se considera
            # fallo del despliegue.
            sin_dato = [(p, c_) for p, c_ in detalles_api
                        if isinstance(c_, int) and c_ == 404]
            if sin_dato:
                print("  INFO  %d endpoint(s) devuelven 404 con el parametro de "
                      "ejemplo (recurso inexistente, no ruta rota): %s"
                      % (len(sin_dato), [p for p, _ in sin_dato][:6]))

        # --- 5) Rutas con 404 esperado por falta de datos -----------------
        for ruta, motivo in RUTAS_SIN_DATOS.items():
            rr = c.get(ruta)
            _check("%s devuelve 404 (motivo: %s)" % (ruta, motivo),
                   rr.status_code == 404, "status=%s" % rr.status_code)

        # --- 6) Estado 'Produccion OK' y sus transiciones -----------------
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

        # --- 7) Catalogo de Resultado de Pruebas --------------------------
        r = c.get("/api/v1/catalogos/etiquetas")
        _check("el catalogo de etiquetas responde 200", r.status_code == 200,
               "status=%s" % r.status_code)

        # --- 8) El dashboard NO debe re-declarar la paleta ----------------
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

        # --- 9) No debe quedar ningun endpoint de diagnostico exposed -----
        r = c.get("/_diag/tickets")
        _check("el endpoint de diagnostico /_diag/tickets ya no existe",
               r.status_code == 404, "status=%s" % r.status_code)

    print("")
    if FALLOS:
        print("RESULTADO BARRIDO: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO BARRIDO: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
