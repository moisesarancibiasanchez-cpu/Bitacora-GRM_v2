# -*- coding: utf-8 -*-
"""Compara la guia recuperada con la que hay en el repo y la instala.

Deja el repo con la version COMPLETA (la que esta publicada) y prepara
dist/ como salida de build, lista para desplegar.
"""
from __future__ import annotations

import difflib
import os
import shutil

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORIGEN = os.path.join(RAIZ, "docs", "onboarding-demo-recuperada", "index.html")
DESTINO = os.path.join(RAIZ, "docs", "onboarding-demo", "index.html")
IMGS_ORIGEN = os.path.join(RAIZ, "docs", "onboarding-demo", "imgs")
DIST = os.path.join(RAIZ, "dist")


def main() -> int:
    nueva = open(ORIGEN, encoding="utf-8").read()
    vieja = open(DESTINO, encoding="utf-8").read()

    print("repo (actual)  : %d chars, %d <section>, %d <h2>"
          % (len(vieja), vieja.count("<section"), vieja.count("<h2")))
    print("recuperada     : %d chars, %d <section>, %d <h2>"
          % (len(nueva), nueva.count("<section"), nueva.count("<h2")))

    sm = difflib.SequenceMatcher(None, vieja.splitlines(), nueva.splitlines(),
                                 autojunk=False)
    print("ratio por lineas: %.4f" % sm.ratio())
    difs = [op for op in sm.get_opcodes() if op[0] != "equal"]
    print("bloques distintos: %d" % len(difs))
    for tag, i1, i2, j1, j2 in difs[:8]:
        print("  %-8s repo[%d:%d] -> recuperada[%d:%d]" % (tag, i1, i2, j1, j2))
        for l in nueva[j1:min(j2, j1 + 3)]:
            print("      + %s" % l.strip()[:120])

    # Se instala la version completa como fuente canonica del repo.
    with open(DESTINO, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(nueva)
    print("")
    print("instalado en docs/onboarding-demo/index.html (%d chars)" % len(nueva))

    # dist/ = salida de build (index.html + imgs/).
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST, exist_ok=True)
    shutil.copy2(DESTINO, os.path.join(DIST, "index.html"))
    if os.path.isdir(IMGS_ORIGEN):
        shutil.copytree(IMGS_ORIGEN, os.path.join(DIST, "imgs"))
    n_imgs = len(os.listdir(os.path.join(DIST, "imgs"))) if os.path.isdir(os.path.join(DIST, "imgs")) else 0
    print("dist/ construido: index.html (%d bytes) + imgs/ (%d ficheros)"
          % (os.path.getsize(os.path.join(DIST, "index.html")), n_imgs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
