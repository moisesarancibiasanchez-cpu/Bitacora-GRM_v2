# -*- coding: utf-8 -*-
"""Arranque limpio REAL de la aplicación (sin mocks, sin datos falsos).

Ejecuta el lifespan real de FastAPI (que es donde vive el guard de
configuración y la aplicación de migraciones) contra una base SQLite
**temporal**, y comprueba que las rutas clave responden.

No toca ninguna base de datos de producción ni la de Railway: la BD se crea
en un archivo temporal y se elimina al terminar.

El escenario replica el de Railway:
  * DEBUG=false
  * SECRET_KEY válida (o ausente: se prueba la generación de start.sh aparte)
  * CORS_ORIGINS con el comodín (degradado a advertencia, no bloqueante)
  * RAILWAY_PUBLIC_DOMAIN presente -> PUBLIC_BASE_URL se deriva solo
"""
from __future__ import annotations

import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def main() -> int:
    db_fd, db_path = tempfile.mkstemp(suffix=".sqlite", prefix="arranque_")
    os.close(db_fd)
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace("\\", "/")
    os.environ["DEBUG"] = "false"
    os.environ["SECRET_KEY"] = "k" * 64
    os.environ["CORS_ORIGINS"] = '["*"]'
    os.environ["RAILWAY_PUBLIC_DOMAIN"] = "bitacora-grmv2-production.up.railway.app"
    os.environ["USE_SQLITE"] = "true"
    os.environ["AUTO_INIT_DB"] = "true"
    os.environ["SEED_DEMO_USERS"] = "true"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    from starlette.testclient import TestClient

    import app.main as main_mod

    _check("import de app.main sin errores", True, "ok")

    # El lifespan real: guard de configuracion + migraciones.
    with TestClient(main_mod.app) as client:
        r = client.get("/health")
        _check("/health responde 200", r.status_code == 200, "status=%s" % r.status_code)
        try:
            cuerpo = r.json()
        except Exception:
            cuerpo = {}
        _check(
            "/health reporta base de datos 'ok'",
            cuerpo.get("database") == "ok",
            "payload=%r" % (cuerpo,),
        )
        _check(
            "/health reporta la app 'Bitacora GRM'",
            cuerpo.get("app") == "Bitácora GRM",
            "payload=%r" % (cuerpo,),
        )

        r = client.get("/", follow_redirects=False)
        _check(
            "/ responde (redirect a login o 200)",
            r.status_code in (200, 302, 307),
            "status=%s" % r.status_code,
        )

        # Login real con las credenciales de la app (endpoint JSON).
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        _check(
            "login admin/admin123 responde 200",
            r.status_code == 200,
            "status=%s cuerpo=%r" % (r.status_code, r.text[:200]),
        )
        if r.status_code == 200:
            cookies = r.headers.get_list("set-cookie")
            tiene_cookie = any("access_token" in c for c in cookies)
            _check("login emite la cookie access_token", tiene_cookie, "cookies=%d" % len(cookies))

        # La cookie de sesión se emite con ``Secure`` (correcto en producción,
        # donde se sirve por HTTPS). El cliente de test habla ``http://``, así
        # que no la reenvía sola: hay que mandarla explícitamente. Sin esto
        # las rutas protegidas responderían 302 a /auth/login y parecería un
        # fallo de la aplicación cuando no lo es.
        token = client.cookies.get("access_token")
        _check("el cliente tiene el token de sesión", bool(token),
              "token=%s..." % (token[:12] if token else "∅"))
        cab = {"Cookie": "access_token=%s" % token} if token else {}

        r = client.get("/kanban", follow_redirects=False, headers=cab)
        _check(
            "/kanban responde 200 (sesion iniciada)",
            r.status_code == 200,
            "status=%s location=%r" % (r.status_code, r.headers.get("location")),
        )
        if r.status_code == 200:
            _check(
                "/kanban renderiza el badge data-resultado-pruebas",
                "data-resultado-pruebas" in r.text,
                "presente en el HTML",
            )

        r = client.get("/dashboard", follow_redirects=False, headers=cab)
        _check(
            "/dashboard responde 200 (sesion iniciada)",
            r.status_code == 200,
            "status=%s location=%r" % (r.status_code, r.headers.get("location")),
        )
        if r.status_code == 200:
            _check(
                "/dashboard inyecta la isla JSON de la paleta",
                'id="cuenta-resultado-paleta"' in r.text,
                "isla presente",
            )
            _check(
                "/dashboard inyecta la isla JSON del fallback",
                'id="cuenta-resultado-fallback"' in r.text,
                "isla presente",
            )

    # --- Verificacion de la migracion aplicada en la BD temporal ----------
    import sqlite3

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        cur.execute("SELECT nombre FROM estados WHERE LOWER(nombre) LIKE '%producci%'")
        estados = cur.fetchall()
        _check(
            "la BD temporal tiene el estado 'Produccion OK' (con acento)",
            len(estados) == 1 and estados[0][0] == "Producción OK",
            "estados=%r" % (estados,),
        )
        cur.execute(
            "SELECT o.nombre, d.nombre FROM transiciones_estado t "
            "JOIN estados o ON o.id = t.estado_origen_id "
            "JOIN estados d ON d.id = t.estado_destino_id "
            "WHERE o.nombre LIKE '%roducci%' OR d.nombre LIKE '%roducci%'"
        )
        trans = cur.fetchall()
        _check(
            "la BD temporal tiene las 3 transiciones del flujo 'Produccion OK'",
            len(trans) == 3,
            "transiciones=%r" % (trans,),
        )
        cur.execute("SELECT COUNT(*) FROM etapas_proyecto")
        n_etapas = cur.fetchone()[0]
        _check("la BD temporal tiene las etapas del proyecto sembradas",
              n_etapas >= 10, "etapas=%s" % n_etapas)
    finally:
        con.close()

    try:
        os.remove(db_path)
    except OSError:
        pass

    print("")
    if FALLOS:
        print("RESULTADO ARRANQUE: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO ARRANQUE: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
