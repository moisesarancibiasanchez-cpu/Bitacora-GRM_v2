"""
Regresiones de V2.007: la aplicacion NO depende de ningun CDN externo.

Contexto del defecto
--------------------
El 2026-10-30 el propietario reporto, con captura de la pestana Network del
navegador, que la pagina /kanban se servia SIN ESTILOS: el logo aparecia
enorme, la maquetacion estaba rota y el Kanban no tenia drag & drop. La
pestana Network mostraba la peticion a ``cdn.tailwindcss.com`` con 0 bytes
tras 40 segundos.

Causa raiz
----------
El proyecto cargaba dos recursos de CDN externos:

  * ``https://cdn.tailwindcss.com`` (la version "Play" de Tailwind, que
    compila las clases EN EL NAVEGADOR),
  * ``https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js``

mas la fuente Inter desde ``fonts.googleapis.com``. Si cualquiera de esas
redes tarda, falla o esta bloqueada, la pagina se queda sin estilos (y el
Kanban se queda sin arrastre). HTMX ya se autoalojaba desde el lote
anterior; faltaba el resto.

Este lote
---------
  * compila Tailwind por adelantado y sirve ``/static/css/tailwind.css``
    (55 KB) en lugar del compilador de 407 KB que se ejecutaba en el
    navegador;
  * autoaloja SortableJS 1.15.2 en ``/static/js/sortable.min.js``;
  * autoaloja la fuente Inter (subconjuntos latin y latin-ext) en
    ``/static/fonts/``.

Que fija esta suite
-------------------
  * que las plantillas no referencien ningun CDN externo,
  * que el CSS compilado, Sortable y la fuente esten versionados,
  * que la configuracion de Tailwind siga cubriendo todo el codigo,
  * y que los tres recursos se sirvan de verdad (200) desde /static.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
DIR_PLANTILLAS = RAIZ / "app" / "templates"
DIR_JS = RAIZ / "app" / "static" / "js"
DIR_CSS = RAIZ / "app" / "static" / "css"
DIR_FUENTES = RAIZ / "app" / "static" / "fonts"

CSS_TAILWIND = DIR_CSS / "tailwind.css"
CSS_FUENTES = DIR_CSS / "fonts.css"
JS_SORTABLE = DIR_JS / "sortable.min.js"
CONFIG = RAIZ / "tailwind.config.js"
ENTRADA = DIR_CSS / "tailwind.src.css"

#: Dominios externos que la aplicacion no debe pedir.
CDN_PROHIBIDOS = (
    "cdn.tailwindcss.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "ajax.googleapis.com",
)

#: Etiquetas que cargan un recurso externo.
RE_RECURSO = re.compile(
    r"""<(script|link|img|iframe)\b[^>]*?\b(?:src|href)\s*=\s*["'](https?://[^"']+)["']""",
    re.I | re.S,
)


def _ficheros_plantillas():
    return [p for p in DIR_PLANTILLAS.rglob("*")
            if p.is_file() and p.suffix in (".html", ".py")]


# ---------------------------------------------------------------------------
# 1. Ninguna dependencia externa
# ---------------------------------------------------------------------------
def test_las_plantillas_no_referencian_ningun_cdn_externo():
    """Ninguna plantilla puede pedir un recurso a un CDN externo."""
    ofensas = []
    for ruta in _ficheros_plantillas():
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        for url in RE_RECURSO.findall(texto):
            if any(dominio in url for dominio in CDN_PROHIBIDOS):
                ofensas.append("%s -> %s" % (ruta.name, url))
    assert not ofensas, "referencias a CDN externos en las plantillas: %s" % ofensas


def test_el_javascript_propio_no_referencia_ningun_cdn_externo():
    """Los .js del proyecto tampoco deben pedir recursos externos."""
    ofensas = []
    for ruta in DIR_JS.rglob("*.js"):
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        for url in RE_RECURSO.findall(texto):
            if any(dominio in url for dominio in CDN_PROHIBIDOS):
                ofensas.append("%s -> %s" % (ruta.name, url))
    assert not ofensas, "referencias a CDN externos en el JS: %s" % ofensas


def test_la_plantilla_base_carga_los_recursos_locales():
    """base.html debe apuntar a los tres recursos autoalojados."""
    html = (DIR_PLANTILLAS / "base.html").read_text(encoding="utf-8")

    assert '/static/css/tailwind.css' in html
    assert '/static/js/sortable.min.js' in html
    assert '/static/css/fonts.css' in html
    # Y no debe quedar el compilador en el navegador ni el config en linea.
    # (Los COMENTARIOS de la plantilla si los mencionan: lo que no puede
    # aparecer es una peticion real a un CDN.)
    assert "tailwind.config =" not in html
    urls = RE_RECURSO.findall(html)
    externas = [u for u in urls
                if any(d in u for d in CDN_PROHIBIDOS)]
    assert not externas, "base.html todavia pide recursos externos: %s" % externas


# ---------------------------------------------------------------------------
# 2. Los recursos estan versionados y completos
# ---------------------------------------------------------------------------
def test_el_css_de_tailwind_esta_compilado_y_versionado():
    """El CSS compilado existe y tiene las utilidades basicas."""
    assert CSS_TAILWIND.exists(), "falta el CSS compilado de Tailwind"
    css = CSS_TAILWIND.read_text(encoding="utf-8")
    assert len(css) > 20000, "el CSS compilado es sospechosamente pequeno"
    for utilidad in (".flex{", ".hidden{", ".grid{", ".rounded-lg{", ".w-10{"):
        assert utilidad in css, "falta la utilidad %s en el CSS" % utilidad


def test_la_entrada_y_la_configuracion_de_tailwind_estan():
    """Debe poder recompilarse el CSS sin herramientas de Python."""
    assert ENTRADA.exists(), "falta la entrada de la compilacion"
    entrada = ENTRADA.read_text(encoding="utf-8")
    assert "@tailwind base;" in entrada
    assert "@tailwind utilities;" in entrada

    assert CONFIG.exists(), "falta tailwind.config.js"
    config = CONFIG.read_text(encoding="utf-8")
    # El escaneo debe cubrir TODO el codigo de la aplicacion: hay markup
    # que se arma en app/core (el badge de Resultado de Pruebas, que usa
    # 'py-[1px]') y no solo en las plantillas.
    assert "./app/**/*.py" in config
    assert "./app/**/*.html" in config
    assert "./app/static/js/**/*.js" in config
    # La fuente del tema se mantiene (la usaba el config en linea).
    assert "Inter" in config


def test_sortable_esta_autohospedado():
    """SortableJS debe estar en el repositorio, con su version."""
    assert JS_SORTABLE.exists(), "falta SortableJS autoalojado"
    texto = JS_SORTABLE.read_text(encoding="utf-8", errors="replace")
    assert "Sortable" in texto
    assert "1.15.2" in texto
    assert len(texto) > 10000


def test_la_fuente_esta_autohospedada():
    """La fuente Inter se sirve desde /static, no desde Google."""
    assert CSS_FUENTES.exists(), "falta el CSS de la fuente autoalojada"
    css = CSS_FUENTES.read_text(encoding="utf-8")
    assert "@font-face" in css
    assert "Inter" in css
    assert "/static/fonts/" in css
    # Ninguna URL externa: ni en las reglas ni en los comentarios.
    externas = RE_RECURSO.findall(css) + re.findall(r"url\(\s*['\"]?(https?://[^)'\"]+)", css)
    assert not externas, "la fuente sigue apuntando a un servidor externo: %s" % externas

    woff2 = list(DIR_FUENTES.glob("*.woff2"))
    assert woff2, "no hay ficheros de fuente"
    for f in woff2:
        assert f.stat().st_size > 1000, "%s esta vacio" % f.name
        assert f.read_bytes()[:4] == b"wOF2", "%s no es un woff2" % f.name


# ---------------------------------------------------------------------------
# 3. Los recursos se sirven de verdad
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def local_client():
    from app.db.base import Base
    from app.db.session import engine
    from app.main import app

    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("ruta", [
    "/static/css/tailwind.css",
    "/static/css/fonts.css",
    "/static/js/sortable.min.js",
    "/static/fonts/inter-latin.woff2",
])
def test_los_recursos_autohospedados_se_sirven(local_client, ruta):
    """Los tres recursos responden 200 desde /static."""
    r = local_client.get(ruta)
    assert r.status_code == 200, "%s -> %s" % (ruta, r.status_code)
    assert len(r.content) > 500, "%s devuelve un cuerpo vacio" % ruta


def test_el_html_servido_no_pide_recursos_externos(local_client):
    """La pagina de acceso no debe cargar ningun recurso de un CDN."""
    r = local_client.get("/auth/login")
    assert r.status_code == 200, r.text
    html = r.text
    externas = [u for u in RE_RECURSO.findall(html)
                if any(d in u for d in CDN_PROHIBIDOS)]
    assert not externas, "la pagina servida pide recursos externos: %s" % externas
    assert '/static/css/tailwind.css' in html
