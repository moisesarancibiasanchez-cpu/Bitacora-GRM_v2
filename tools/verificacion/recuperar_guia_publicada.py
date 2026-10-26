# -*- coding: utf-8 -*-
"""Recupera la guía de Onboarding publicada al repo, separando el contenido
del proyecto del andamiaje inyectado por la plataforma de hosting.

Situación
---------
La versión publicada (https://dshj4lrwlf4x.space.mcode.io) es un SUPERCONJUNTO
del archivo que hay en el repo: se le añadieron las secciones de "Indicador de
Resultado de Pruebas" y "Cuenta de Resultado" (trabajo de la V1.001) en un
árbol de trabajo que nunca se commiteó.

La plataforma de hosting inyecta además bloques propios que NO son contenido
del proyecto:
  1) script de resaltado de iframe (x2, para el preview cross-origin)
  2) CSS del globo flotante
  3) HTML del globo flotante ("Created by MiniMax Agent")
  4) script del globo flotante

Lo que NO es andamiaje y hay que CONSERVAR:
  - el script del proyecto que resalta la sección activa del índice (TOC)
  - el script del proyecto que reemplaza el placeholder {{build_date}}
  - el placeholder {{build_date}} del pie de página

Salida:
  docs/onboarding-demo-recuperada/index.html   (contenido del proyecto)
  docs/onboarding-demo-recuperada/_andamiaje_plataforma.txt (lo quitado)
"""
from __future__ import annotations

import os
import re

import httpx

URL = "https://dshj4lrwlf4x.space.mcode.io/"
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SALIDA = os.path.join(RAIZ, "docs", "onboarding-demo-recuperada")

# Marcas EXCLUSIVAS del andamiaje de la plataforma. {{build_date}} NO se
# incluye: ese placeholder y el script que lo reemplaza son del proyecto.
MARCAS_PLATAFORMA = (
    "Iframe 元素高亮注入脚本",
    "__iframeHighlightInitialized",
    "__iframeHighlightCleanup",
    "initFloatingBall",
    "minimax-floating-ball",
    "minimax-close-icon",
    "minimax-ball-text",
    "minimax-logo-wave",
)
# Marcas que deben seguir en el contenido recuperado.
MARCAS_PROYECTO = (
    "Highlight active section in TOC",
    "Replace build date placeholder",
    "{{build_date}}",
)

RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
RE_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
RE_TOKEN_DIV = re.compile(r"</?div\b[^>]*>", re.IGNORECASE)


def _quitar_elemento(html: str, apertura: str) -> str:
    """Elimina un elemento HTML completo contando la anidamiento de etiquetas.

    Escanea los tokens de apertura y cierre de la etiqueta para saber dónde
    termina el elemento, en vez de usar una expresión regular que se rompería
    con los <div> anidados del globo flotante.
    """
    ini = html.find(apertura)
    if ini == -1:
        return html
    fin_etiqueta = html.find(">", ini)
    if fin_etiqueta == -1:
        return html
    nombre = html[ini + 1:fin_etiqueta].split()[0].rstrip("/>")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", nombre):
        return html

    profundidad = 0
    # El escaneo arranca DESPUES de la etiqueta de apertura: si se incluyera,
    # la profundidad nunca volvería a 0 en el cierre correcto.
    pos = fin_etiqueta + 1
    while True:
        m = RE_TOKEN_DIV.search(html, pos)
        if not m:
            break
        token = m.group(0)
        if token.startswith("</"):
            if profundidad == 0:
                fin = html.find(">", m.start())
                return html[:ini] + html[fin + 1:]
            profundidad -= 1
        else:
            # Una etiqueta de cierre propia (<div ... />) no aumenta el nivel.
            if not token.rstrip().endswith("/>"):
                profundidad += 1
        pos = m.end()
    return html


def main() -> int:
    r = httpx.get(URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    html = r.text
    print("descargado: %d caracteres" % len(html))

    bloques = RE_SCRIPT.findall(html)
    plataforma, proyecto = [], []
    for b in bloques:
        if any(m in b for m in MARCAS_PLATAFORMA):
            plataforma.append(b)
        else:
            proyecto.append(b)
    print("bloques <script>: %d (proyecto=%d, plataforma=%d)"
          % (len(bloques), len(proyecto), len(plataforma)))
    for i, b in enumerate(proyecto):
        marcas = [m for m in MARCAS_PROYECTO if m in b]
        print("   proyecto  [%d] %5d chars  marcas=%s" % (i, len(b), marcas))
    for i, b in enumerate(plataforma):
        marcas = [m for m in MARCAS_PLATAFORMA if m in b]
        print("   plataforma[%d] %5d chars  marcas=%s" % (i, len(b), marcas))

    # 1) Se quitan los scripts de la plataforma.
    limpio = html
    for b in plataforma:
        limpio = limpio.replace(b, "")

    # 2) Se quita el CSS de la plataforma.
    estilos_plataforma = [s for s in RE_STYLE.findall(limpio)
                          if any(m in s for m in MARCAS_PLATAFORMA)]
    for s in estilos_plataforma:
        limpio = limpio.replace(s, "")

    # 3) Se quita el globo flotante (HTML con <div> anidados).
    limpio = _quitar_elemento(limpio, '<div id="minimax-floating-ball">')

    # 4) Limpieza de restos vacíos.
    limpio = re.sub(r"<script\b[^>]*>\s*</script>\s*", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"<style\b[^>]*>\s*</style>\s*", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio)

    print("")
    print("tras quitar el andamiaje: %d caracteres" % len(limpio))

    comprobaciones = [
        ("secciones <section> = 24", limpio.count("<section") == 24,
         str(limpio.count("<section"))),
        ("titulo intacto",
         "<title>Bitácora GRM v2 — Guía de Onboarding para Usuarios</title>" in limpio, ""),
        ("seccion Indicador de Resultado de Pruebas",
         "Indicador de Resultado de Pruebas" in limpio, ""),
        ("seccion Cuenta de Resultado", "Cuenta de Resultado" in limpio, ""),
        ("script del proyecto (TOC) conservado",
         "Highlight active section in TOC" in limpio, ""),
        ("script del proyecto (build_date) conservado",
         "Replace build date placeholder" in limpio, ""),
        ("placeholder {{build_date}} conservado", "{{build_date}}" in limpio, ""),
        ("sin script de iframe", "Iframe 元素高亮注入脚本" not in limpio, ""),
        ("sin globo flotante", "minimax-floating-ball" not in limpio, ""),
        ("sin marca 'Created by MiniMax Agent'",
         "Created by MiniMax Agent" not in limpio, ""),
        ("favicon relativo intacto", 'href="imgs/logo.svg"' in limpio, ""),
        ("el documento cierra bien", limpio.rstrip().endswith("</html>"), ""),
    ]
    print("")
    fallos = 0
    for nombre, ok, detalle in comprobaciones:
        print(("PASA " if ok else "FALLA ") + nombre + (" :: " + detalle if detalle else ""))
        if not ok:
            fallos += 1

    if fallos:
        print("")
        print("NO se escribe nada: la recuperación no superó las comprobaciones.")
        return 1

    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(limpio)
    with open(os.path.join(SALIDA, "_andamiaje_plataforma.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("\n\n<!-- ===== ANDAMIAJE DE LA PLATAFORMA (quitado) ===== -->\n\n"
                 .join(plataforma + estilos_plataforma))
    print("")
    print("escrito: %s" % os.path.join(SALIDA, "index.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
