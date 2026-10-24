# -*- coding: utf-8 -*-
"""Verifica la integridad de la salida de build dist/ antes de publicarla.

Comprueba:
  * index.html existe en la raiz de dist/ y es un HTML con <html> y <body>
  * los 24 recursos de imgs/ referenciados existen en dist/imgs/
  * los enlaces internos (#ancla) apuntan a ids que existen
  * no queda andamiaje de la plataforma de hosting
  * el documento cierra bien y no tiene placeholders sin resolver (salvo
    {{build_date}}, que rellena el propio script del proyecto)
"""
from __future__ import annotations

import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(RAIZ, "dist")

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def main() -> int:
    index = os.path.join(DIST, "index.html")
    _check("dist/index.html existe", os.path.isfile(index),
           "ruta=%s" % index)
    if not os.path.isfile(index):
        return 1
    html = open(index, encoding="utf-8").read()
    print("      tamano: %d bytes" % os.path.getsize(index))

    _check("es un documento HTML completo",
           html.lstrip().lower().startswith("<!doctype html")
           and "<html" in html.lower() and "</html>" in html.lower(), "")
    _check("tiene las 24 secciones", html.count("<section") == 24,
           str(html.count("<section")))
    _check("incluye la seccion de Resultado de Pruebas",
           "Indicador de Resultado de Pruebas" in html, "")
    _check("incluye la seccion Cuenta de Resultado",
           "Cuenta de Resultado" in html, "")

    # Recursos referenciados.
    refs = set(re.findall(r'(?:src|href)\s*=\s*["\'](imgs/[^"\']+)["\']', html))
    faltan = [r for r in sorted(refs)
              if not os.path.isfile(os.path.join(DIST, r.replace("/", os.sep)))]
    _check("todos los recursos de imgs/ referenciados existen (%d)" % len(refs),
           not faltan, "faltan=%r" % faltan)

    # Anclas internas.
    ids = set(re.findall(r'id\s*=\s*["\']([^"\']+)["\']', html))
    anclas = set(re.findall(r'href\s*=\s*["\']#([^"\']+)["\']', html))
    rotas = sorted(a for a in anclas if a not in ids)
    _check("todas las anclas internas resuelven (%d anclas)" % len(anclas),
           not rotas, "rotas=%r" % rotas[:8])

    # Andamiaje de la plataforma.
    for marca in ("minimax-floating-ball", "minimax-close-icon",
                  "Created by MiniMax Agent", "Iframe 元素高亮注入脚本"):
        _check("sin andamiaje de la plataforma: %s" % marca, marca not in html, "")

    # Placeholders.
    otros = [m for m in re.findall(r"\{\{[a-zA-Z_]+\}\}", html)
             if m != "{{build_date}}"]
    _check("no quedan placeholders sin resolver (salvo {{build_date}})",
           not otros, "otros=%r" % otros)
    _check("el placeholder {{build_date}} tiene su script que lo reemplaza",
           "Replace build date placeholder" in html, "")

    print("")
    if FALLOS:
        print("RESULTADO DIST: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO DIST: la salida de build esta lista para publicar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
