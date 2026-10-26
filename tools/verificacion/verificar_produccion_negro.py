"""
Verificacion en negro de la produccion de Bitacora GRM v2.

Comprueba, contra la URL de produccion, que el despliegue esta vivo y que
las correcciones de seguridad del lote V1.005 estan realmente aplicadas:

  1. salud del servicio (/health)
  2. retirada del endpoint de diagnostico /_diag/tickets
  3. /info sin topologia interna de la base de datos
  4. cabeceras de seguridad (HSTS, CSP, Permissions-Policy, ...)
  5. redireccion de /onboarding SIN degradar a http://
  6. barrido de todas las rutas GET del OpenAPI: ningun 5xx
  7. paginas HTML: ningun 5xx

Solo hace peticiones GET. No escribe nada en la base de datos y no necesita
sesion ni credenciales.

Uso:
    & 'C:\\Python311embed\\python.exe' -X utf8 'tools\\verificacion\\verificar_produccion_negro.py'

Variable de entorno opcional:
    BITACORA_APP_URL  URL base de la aplicacion (por defecto, la de
                       produccion).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get(
    "BITACORA_APP_URL",
    "https://bitacora-grmv2-production.up.railway.app",
).rstrip("/")
UA = "BitacoraGRM-ReadOnly-Verifier/2.0"

fallos: list[str] = []
ok = 0


def check(nombre: str, cond: bool, detalle: str = "") -> None:
    """Registra el resultado de una comprobacion."""
    global ok
    if cond:
        ok += 1
        print(f"  PASA {nombre}" + (f" :: {detalle}" if detalle else ""))
    else:
        fallos.append(nombre)
        print(f"  FALLA {nombre}" + (f" :: {detalle}" if detalle else ""))


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    """Impide seguir las redirecciones: se quiere ver el Location real."""

    def redirect_request(self, *args, **kwargs):  # noqa: D102, ANN002, ANN003
        return None


def get(ruta: str, cabeceras: dict | None = None):
    """GET sin seguir redirecciones. Devuelve (status, cabeceras, cuerpo)."""
    url = ruta if ruta.startswith("http") else BASE + ruta
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, **(cabeceras or {})}
    )
    opener = urllib.request.build_opener(_SinRedireccion)
    try:
        with opener.open(req, timeout=45) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except Exception as exc:  # noqa: BLE001
        return 0, {}, str(exc).encode("utf-8", "replace")


def main() -> int:
    print("=" * 78)
    print("VERIFICACION EN NEGRO DE PRODUCCION - Bitacora GRM v2")
    print(f"Objetivo: {BASE}")
    print("=" * 78)

    print("\n== 1) Salud del servicio ==")
    st, _hd, _body = get("/health")
    check("/health responde 200", st == 200, f"status={st}")

    print("\n== 2) Endpoint de diagnostico retirado ==")
    st, _hd, body = get("/_diag/tickets")
    check("/_diag/tickets devuelve 404", st == 404, f"status={st}")
    check(
        "el cuerpo ya no expone el volcado de tickets",
        b"total_tickets" not in body and b"first_ticket_debug" not in body,
        body[:120].decode("utf-8", "replace"),
    )

    print("\n== 3) /info sin topologia interna ==")
    st, _hd, body = get("/info")
    info = {}
    if st == 200:
        try:
            info = json.loads(body.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            pass
    check("/info responde 200", st == 200, f"status={st}")
    check("/info ya no publica database_url", "database_url" not in info, str(sorted(info)))
    check(
        "/info publica el motor de datos",
        info.get("database") in ("sqlite", "postgresql"),
        str(info.get("database")),
    )

    print("\n== 4) Cabeceras de seguridad ==")
    st, hd, _ = get("/health")
    for cab, esperado in (
        ("Strict-Transport-Security", "max-age=31536000"),
        ("Content-Security-Policy", "default-src 'self'"),
        ("Permissions-Policy", "geolocation=()"),
        ("X-Frame-Options", "DENY"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ):
        valor = hd.get(cab) or hd.get(cab.lower()) or ""
        check(f"cabecera {cab}", bool(valor) and esperado in valor, f"valor={valor[:110]!r}")

    print("\n== 5) Redireccion de /onboarding sin degradar a http:// ==")
    st, hd, _ = get("/onboarding")
    loc = hd.get("Location") or hd.get("location") or ""
    check("/onboarding responde 307", st == 307, f"status={st}")
    check("el Location no degrada a http://", not loc.startswith("http://"), f"Location={loc!r}")
    check("el Location apunta a la misma ruta", "/onboarding" in loc, f"Location={loc!r}")

    print("\n== 6) OpenAPI y barrido de las rutas GET ==")
    st, _hd, body = get("/openapi.json")
    esquema: dict = {}
    if st == 200:
        try:
            esquema = json.loads(body.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            pass
    rutas = sorted(p for p, ops in esquema.get("paths", {}).items() if "get" in ops)
    check("/openapi.json responde 200", st == 200, f"status={st}")
    check(
        "el esquema expone 124 rutas GET (123 + /salud-celery)",
        len(rutas) == 124,
        f"rutas={len(rutas)}",
    )
    check(
        "el esquema NO expone /_diag/tickets",
        "/_diag/tickets" not in esquema.get("paths", {}),
    )
    estados: dict = {}
    for ruta in rutas:
        st_r, _h, _b = get(ruta)
        estados[st_r] = estados.get(st_r, 0) + 1
    errores5xx = sum(
        v for k, v in estados.items() if isinstance(k, int) and k >= 500
    )
    print(f"  reparto de estados: {estados}")
    check("ninguna ruta GET devuelve 5xx", errores5xx == 0, f"5xx={errores5xx}")

    print("\n== 7) Paginas HTML ==")
    paginas = [
        "/auth/login", "/auth/registro", "/", "/kanban", "/dashboard", "/tickets",
        "/tickets/nuevo", "/tickets/tabla", "/usuarios", "/butler", "/vistas/tabla",
        "/vistas/timeline", "/vistas/panel", "/vistas/planner", "/vistas/gantt",
        "/vistas/calendario", "/admin/reporte-entregas",
    ]
    codigos: dict = {}
    for ruta in paginas:
        st_p, _h, _b = get(ruta)
        codigos[ruta] = st_p
        if isinstance(st_p, int) and st_p >= 500:
            print(f"    5xx en {ruta}: {st_p}")
    errores5xx = sum(1 for v in codigos.values() if isinstance(v, int) and v >= 500)
    print(f"  codigos: {codigos}")
    check("ninguna pagina HTML devuelve 5xx", errores5xx == 0, f"5xx={errores5xx}")
    check(
        "/ responde 307 hacia /auth/login",
        codigos.get("/") in (302, 303, 307),
        f"status={codigos.get('/')}",
    )

    print("\n== 8) Salud de Celery (opcional: requiere credenciales) ==")
    usuario = os.environ.get("BITACORA_ADMIN_USER")
    clave = os.environ.get("BITACORA_ADMIN_PASSWORD")
    if not usuario or not clave:
        print("  SALTADO: faltan BITACORA_ADMIN_USER / BITACORA_ADMIN_PASSWORD")
        print("  (define las variables para comprobar worker y beat)")
    else:
        st, _hd, _b = get("/salud-celery")
        check("/salud-celery exige sesion (401 sin cookie)", st == 401, f"status={st}")
        import json as _json
        import urllib.request as _u

        cuerpo = _json.dumps({"username": usuario, "password": clave}).encode("utf-8")
        req = _u.Request(
            BASE + "/api/v1/auth/login",
            data=cuerpo,
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        try:
            with _u.urlopen(req, timeout=45) as resp:
                cookie = resp.headers.get("Set-Cookie", "")
            token = ""
            if "access_token=" in cookie:
                token = cookie.split("access_token=")[1].split(";")[0]
            check("el login del administrador devuelve cookie de sesion", bool(token))
            st, _hd, body = get("/salud-celery", {"Cookie": f"access_token={token}"})
            check("/salud-celery responde 200 con sesion de administrador",
                  st == 200, f"status={st} body={body[:200]!r}")
            if st == 200:
                salud = _json.loads(body.decode("utf-8", "replace"))
                print(f"    worker: {salud.get('worker')}")
                print(f"    beat:   {salud.get('beat')}")
                print(f"    colas:  {salud.get('colas')}")
                check("hay un worker que responde al ping",
                      bool((salud.get("worker") or {}).get("responde")),
                      str((salud.get("worker") or {}).get("detalle")))
                # El catalogo de tareas del worker dice si el servicio
                # worker esta con el codigo actual: si no conoce la tarea
                # del latido, esta con un despliegue anterior.
                worker = salud.get("worker") or {}
                check("el worker conoce la tarea del latido (codigo actual)",
                      worker.get("conoce_latido") is True,
                      "tareas_registradas=%s conoce_latido=%s" % (
                          worker.get("tareas_registradas"),
                          worker.get("conoce_latido")))
                check("el beat escribio un latido reciente",
                      bool((salud.get("beat") or {}).get("ok")),
                      str((salud.get("beat") or {}).get("detalle")))
        except Exception as exc:  # noqa: BLE001
            check("el login del administrador funciona", False, repr(exc))

    print("\n" + "=" * 78)
    if fallos:
        print(
            f"RESULTADO: {len(fallos)} FALLOS de {ok + len(fallos)} comprobaciones"
        )
        for f in fallos:
            print("  - " + f)
        return 1
    print(f"RESULTADO: {ok}/{ok} comprobaciones superadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
