# -*- coding: utf-8 -*-
"""Verifica el sitio recien desplegado: contenido, recursos y anclas."""
from __future__ import annotations

import re
import sys
import urllib.parse

import httpx

URL = sys.argv[1] if len(sys.argv) > 1 else "https://8ww9qr1jzjgp8.space.minimax.io"

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def main() -> int:
    with httpx.Client(timeout=40, follow_redirects=True) as c:
        r = c.get(URL + "/")
        _check("el sitio responde 200", r.status_code == 200, "status=%s" % r.status_code)
        if r.status_code != 200:
            return 1
        html = r.text
        print("      %d caracteres, content-type=%s" % (len(html), r.headers.get("content-type")))

        _check("titulo correcto",
               "<title>Bitácora GRM v2 — Guía de Onboarding para Usuarios</title>" in html, "")
        _check("24 secciones", html.count("<section") == 24, str(html.count("<section")))
        _check("seccion Indicador de Resultado de Pruebas",
               "Indicador de Resultado de Pruebas" in html, "")
        _check("seccion Cuenta de Resultado", "Cuenta de Resultado" in html, "")

        # Recursos.
        refs = sorted(set(re.findall(
            r'(?:src|href)\s*=\s*["\'](imgs/[^"\']+)["\']', html)))
        rotos = []
        for ref in refs:
            rr = c.get(urllib.parse.urljoin(URL + "/", ref))
            if rr.status_code != 200:
                rotos.append((ref, rr.status_code))
        _check("los %d recursos de imgs/ cargan" % len(refs), not rotos, "rotos=%r" % rotos)

        # Anclas internas.
        ids = set(re.findall(r'id\s*=\s*["\']([^"\']+)["\']', html))
        anclas = sorted(set(re.findall(r'href\s*=\s*["\']#([^"\']+)["\']', html)))
        rotas = [a for a in anclas if a not in ids]
        _check("las %d anclas internas resuelven" % len(anclas), not rotas, "rotas=%r" % rotas)

        # La plataforma debe haber inyectado su andamiaje (marca de la plataforma).
        print("      andamiaje de la plataforma inyectado: %s"
              % ("si" if ("minimax-floating-ball" in html or
                          "Iframe 元素高亮注入脚本" in html) else "no"))
        _check("el placeholder {{build_date}} esta presente para la plataforma",
                "{{build_date}}" in html, "")

    print("")
    if FALLOS:
        print("RESULTADO SITIO: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO SITIO: el sitio desplegado esta completo y sin recursos rotos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
