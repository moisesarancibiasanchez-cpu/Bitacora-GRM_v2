# -*- coding: utf-8 -*-
"""Barrido ANONIMO de rutas: comprueba que sin sesion no se sirve nada.

Por que existe
--------------
``barrer_rutas.py`` recorre las rutas CON la sesion del administrador
administrado. Ese barrido dice que la app funciona, pero no dice que la
app este CERRADA: una ruta que se olvidara de pedir sesion seguiria
devolviendo 200 con datos y el barrido autenticado no lo detectaria.

Este barrido hace lo contrario: pide TODAS las rutas GET **sin cookie y sin
token** y exige que ninguna devuelva datos. La referencia de "sin datos" es
la propia pantalla de login: las paginas HTML, cuando no hay sesion, se
sirven redirigidas al formulario de autenticacion, y ese HTML es
identico byte a byte en todas ellas.

Criterios
----------
* 200 con un cuerpo DISTINTO al de la pantalla de login -> FALLO: se ha
  servido algo a un visitante anonimo.
* 5xx -> FALLO: error de servidor.
* 401 / 403 / 302 / 307 / 404 -> correcto (protegida, redireccion o
  inexistente).
* Ademas se buscan "huellas" de datos reales (correos, codigos de ticket,
  identificadores) en el cuerpo anonimo. Cualquier huella que NO aparezca
  tambien en la pantalla de login es una fuga.

Ruido conocido
--------------
La pantalla de login incluye la CDN de SortableJS (``sortablejs@1.15.2``),
que tiene forma de direccion de correo pero no lo es. Se excluye
explicitamente para que el detector no se dispare por un falso positivo.

Uso:
    python tools/verificacion/barrer_anonimo.py [BASE_URL]

No requiere credenciales: hace unicamente peticiones GET de solo lectura.
Devuelve 0 si todo esta bien y 1 si hay alguna fuga.
"""
from __future__ import annotations

import json
import re
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://bitacora-grmv2-production.up.railway.app"

#: Rutas publicas por diseno: no deben exigir sesion.
RUTAS_PUBLICAS = {
    "/auth/login",
    "/auth/registro",
    "/health",
    "/ready",
    "/info",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/p/{slug}",
    "/dev/inbox",
    "/dev/inbox/",
}

#: Rutas del OpenAPI que son endpoints de FICHERO, no paginas: su codigo
#: depende de que exista el recurso, no de la sesion.
RUTAS_DE_FICHERO = ("/exportar", "/descargar", "/download")

#: Cadenas con forma de correo que no son correos (CDN de la plantilla).
RUIDO_CONOCIDO = {
    "sortablejs@1.15.2",
}

#: Parametros de ruta: se sustituyen por un valor concreto para poder pedir
#: la ruta. Un 404 por inexistencia NO es una fuga.
PARAMETROS = {
    "ticket_id": "1",
    "id": "1",
    "usuario_id": "1",
    "estado_id": "1",
    "tabla_id": "1",
    "tablero_id": "1",
    "espacio_id": "1",
    "etapa_id": "1",
    "campo_id": "1",
    "regla_id": "1",
    "etiqueta_id": "1",
    "comentario_id": "1",
    "adjunto_id": "1",
    "slug": "demo",
    "reporte_id": "1",
    "categoria_id": "1",
    "prioridad_id": "1",
    "tipo_id": "1",
    "subcategoria_id": "1",
}

#: Huellas de datos reales dentro del cuerpo de una respuesta.
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RE_TICKET = re.compile(r"\bTKT-[A-Za-z0-9\-]{2,}\b")

FALLOS: list[str] = []


def _check(nombre: str, condicion: bool, detalle: str = "") -> None:
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def _resolver(path: str) -> str:
    for nombre in re.findall(r"\{(\w+)\}", path):
        path = path.replace("{%s}" % nombre, PARAMETROS.get(nombre, "1"))
    return path


def _huellas(texto: str) -> set[str]:
    """Extrae las huellas de datos reales de un cuerpo HTML/JSON."""
    huellas = set()
    for valor in RE_EMAIL.findall(texto or ""):
        if valor.lower() in RUIDO_CONOCIDO:
            continue
        huellas.add(valor.lower())
    for valor in RE_TICKET.findall(texto or ""):
        huellas.add(valor)
    return huellas


def main() -> int:
    print("=" * 78)
    print(" BARRIDO ANONIMO de rutas contra %s" % BASE)
    print(" (sin sesion: comprueba que no se sirve nada a un visitante)")
    print("=" * 78)

    with httpx.Client(base_url=BASE, timeout=45, follow_redirects=False) as c:
        # --- 1) Referencia: la pantalla de login -----------------------------
        r = c.get("/auth/login")
        _check("/auth/login responde 200 (referencia)", r.status_code == 200,
               "status=%s" % r.status_code)
        if r.status_code != 200:
            print("ABORTANDO: sin la pantalla de login no hay referencia que comparar.")
            return 1
        base_cuerpo = r.content
        base_texto = r.text
        base_huellas = _huellas(base_texto)
        print("      cuerpo de referencia: %d bytes, %d huellas" % (
            len(base_cuerpo), len(base_huellas)))

        # --- 2) Esquema real del despliegue ----------------------------------
        r = c.get("/openapi.json")
        _check("se puede leer /openapi.json anonimamente", r.status_code == 200,
               "status=%s" % r.status_code)
        if r.status_code != 200:
            print("ABORTANDO: sin el esquema no se pueden derivar las rutas.")
            return 1
        esquema = r.json()
        rutas = sorted(
            ruta for ruta, definicion in (esquema.get("paths") or {}).items()
            if "get" in (definicion or {})
        )
        print("      rutas GET del esquema: %d" % len(rutas))

        # --- 3) Barrido ------------------------------------------------------
        print("")
        print("  RUTAS GET SIN SESION")
        print("  " + "-" * 42)
        fugas = []
        errores = []
        servidas = []
        for ruta in rutas:
            if ruta in RUTAS_PUBLICAS:
                continue
            resuelta = _resolver(ruta)
            try:
                rr = c.get(resuelta)
                code = rr.status_code
                cuerpo = rr.content
            except Exception as exc:  # pragma: no cover
                errores.append((ruta, "ERROR %s" % exc))
                continue

            if code >= 500:
                errores.append((ruta, "HTTP %s" % code))
                continue
            if code == 200:
                if cuerpo == base_cuerpo:
                    # La pagina se sirvio el formulario de login: correcto.
                    continue
                # ¿Es un binario legitimo (CSV, PDF) served sin sesion?
                if any(m in ruta for m in RUTAS_DE_FICHERO):
                    servidas.append((ruta, "contenido=%s bytes" % len(cuerpo)))
                    continue
                fugas.append((ruta, "HTTP 200 con %d bytes distintos de la pantalla de login" % len(cuerpo)))
                continue
            # 401 / 403 / 302 / 307 / 404: correcto.

        for ruta, detalle in fugas:
            print("  FUGA    %-45s %s" % (ruta, detalle))
        for ruta, detalle in errores:
            print("  ERROR   %-45s %s" % (ruta, detalle))
        for ruta, detalle in servidas:
            print("  REVISAR %-45s %s" % (ruta, detalle))

        print("")
        _check("ninguna ruta GET sirve contenido a un anonimo", not fugas,
               "fugas=%d %r" % (len(fugas), [f[0] for f in fugas[:8]]))
        _check("ninguna ruta GET produce un error de servidor", not errores,
               "errores=%d %r" % (len(errores), [e[0] for e in errores[:8]]))
        _check("no hay rutas que sirvan ficheros sin sesion", not servidas,
               "revisar=%d %r" % (len(servidas), [s[0] for s in servidas[:8]]))

        # --- 4) Huellas de datos en las respuestas anonimas ------------------
        print("")
        print("  HUELLAS DE DATOS (correos / codigos de ticket)")
        print("  " + "-" * 42)
        fugas_huella = []
        for ruta in rutas:
            if ruta in RUTAS_PUBLICAS:
                continue
            resuelta = _resolver(ruta)
            try:
                rr = c.get(resuelta)
            except Exception:
                continue
            if rr.status_code != 200 or rr.content == base_cuerpo:
                continue
            nuevas = _huellas(rr.text) - base_huellas
            if nuevas:
                fugas_huella.append((ruta, sorted(nuevas)[:5]))
        for ruta, valores in fugas_huella:
            print("  FUGA    %-45s %r" % (ruta, valores))
        _check("ninguna respuesta anonima contiene huellas de datos reales",
               not fugas_huella,
               "fugas=%d %r" % (len(fugas_huella), [f[0] for f in fugas_huella[:8]]))

        # --- 5) Caso concreto queoriginó esta herramienta -------------------
        r = c.get("/api/v1/auth/cambiar-password-modal")
        _check(
            "el modal de cambio de contraseña exige sesión (401/403)",
            r.status_code in (401, 403),
            "status=%s" % r.status_code,
        )

    print("")
    if FALLOS:
        print("RESULTADO: %d comprobacion(es) fallida(s)" % len(FALLOS))
        for f in FALLOS:
            print("  - %s" % f)
        return 1
    print("RESULTADO: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
