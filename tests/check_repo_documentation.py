"""Comprueba enlaces internos de los Markdown y recuentos OpenAPI del repo.

Uso desde la raiz del repositorio:

    C:\\Python311embed\\python.exe -X utf8 tests\\check_repo_documentation.py

Devuelve 0 si no encuentra enlaces rotos y 1 si encuentra alguno. El modo
``--counts`` imprime el inventario OpenAPI y de referencias HTML/JS sin hacer
peticiones de red.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# La app crea su engine al importarse. Apuntarlo a la BD temporal de tests
# evita que una comprobacion documental abra la base configurada en el shell.
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + (RAIZ / "tests" / "tmp" / "documentation_audit.sqlite").as_posix(),
)
os.environ.setdefault("SECRET_KEY", "clave-solo-para-auditoria-documental-0123456789")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("AUTO_INIT_DB", "false")
os.environ.setdefault("SEED_DEMO_USERS", "false")

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
HTML_ID_RE = re.compile(r"<(?:a|span|div)\b[^>]*(?:id|name)=[\"']([^\"']+)[\"']", re.I)
HTML_HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
JS_URL_RE = re.compile(r"[\"']((?:/api/|/)[A-Za-z0-9_./{}?=&:-]+)[\"']")
TEMPLATE_ATTR_RE = re.compile(
    r"\b(?:href|src|action|hx-get|hx-post|hx-put|hx-patch|hx-delete|"
    r"hx-action)=[\"']([^\"']+)[\"']",
    re.I,
)
EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "tests/tmp",
}


def markdown_files() -> list[Path]:
    """Devuelve los Markdown versionables del repositorio."""
    resultado: list[Path] = []
    for path in RAIZ.rglob("*.md"):
        partes_relativos = path.relative_to(RAIZ).parts
        if any(parte in EXCLUDED_DIRS for parte in partes_relativos[:-1]):
            continue
        resultado.append(path)
    return sorted(resultado)


def normalizar_slug(texto: str) -> str:
    """Aproxima el slug de encabezado usado por GitHub."""
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = texto.strip().lower()
    texto = re.sub(r"[^\w\- ]", "", texto, flags=re.UNICODE)
    texto = re.sub(r"\s+", "-", texto)
    return texto


def anclas_documento(path: Path) -> set[str]:
    """Extrae identificadores y slugs de encabezado de un Markdown."""
    anclas: set[str] = set()
    dentro_de_codigo = False
    for linea in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if linea.lstrip().startswith("```"):
            dentro_de_codigo = not dentro_de_codigo
            continue
        if dentro_de_codigo:
            continue
        encabezado = HEADING_RE.match(linea)
        if encabezado:
            anclas.add(normalizar_slug(encabezado.group(1)))
        anclas.update(HTML_ID_RE.findall(linea))
    return anclas


def extraer_destinos(texto: str):
    """Extrae destinos de enlaces Markdown y devuelve (destino, linea)."""
    destinos = []
    dentro_de_codigo = False
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if linea.lstrip().startswith("```"):
            dentro_de_codigo = not dentro_de_codigo
            continue
        if dentro_de_codigo:
            continue
        linea_sin_codigo = re.sub(r"`[^`]*`", "", linea)
        for coincidencia in LINK_RE.finditer(linea_sin_codigo):
            destino = coincidencia.group(1).strip()
            if destino.startswith("<") and ">" in destino:
                destino = destino[1 : destino.index(">")]
            else:
                destino = destino.split(None, 1)[0]
            destinos.append((destino, numero))
        referencia = REFERENCE_RE.match(linea_sin_codigo)
        if referencia:
            destinos.append((referencia.group(1), numero))
    return destinos


def cargar_rutas_app() -> set[str]:
    """Carga las rutas FastAPI/OpenAPI sin realizar solicitudes de red."""
    from app.main import app

    rutas = {
        getattr(ruta, "path", "")
        for ruta in app.routes
        if getattr(ruta, "path", "").startswith("/")
    }
    try:
        esquema = app.openapi()
    except Exception:
        return rutas
    rutas.update(ruta for ruta in esquema.get("paths", {}) if ruta.startswith("/"))
    return rutas


def ruta_coincide(ruta: str, rutas: set[str]) -> bool:
    """Compara una URL concreta con las rutas parametrizadas de FastAPI."""
    if not ruta.startswith("/"):
        return False
    ruta = ruta.rstrip("/") or "/"
    for plantilla in rutas:
        if plantilla == ruta:
            return True
        partes = re.split(r"(\{[^}]+\})", plantilla)
        patron = "".join(
            "[^/]+" if parte.startswith("{") else re.escape(parte)
            for parte in partes
        )
        try:
            if re.match("^" + patron + "$", ruta):
                return True
        except re.error:
            continue
    return False


def comprobar_enlaces() -> tuple[list[str], int]:
    """Devuelve (detalles de enlaces rotos, total de enlaces comprobados)."""
    rutas_app = cargar_rutas_app()
    rotos: list[str] = []
    comprobados = 0
    cache_anclas: dict[Path, set[str]] = {}

    for documento in markdown_files():
        texto = documento.read_text(encoding="utf-8", errors="replace")
        for destino, linea in extraer_destinos(texto):
            if not destino:
                continue
            if destino.startswith("#"):
                # Ancla dentro del MISMO documento.
                #
                # Antes estos enlaces se ignoraban por completo, y por eso
                # los 39 enlaces a '#sec-N' de la guia de onboarding
                # (que NO definia esas anclas) pasaban inadvertidos: el
                # contador ENLACES_COMPROBADOS salia en 0 y no habia
                # ninguna comprobacion que los delatara.
                fragmento = unquote(destino[1:])
                if not fragmento:
                    continue
                comprobados += 1
                if fragmento.lower() == "top":
                    # '#top' es un fragmento reservado por el navegador:
                    # si no existe un elemento con ese id, el navegador
                    # desplaza la pagina al principio. No es un enlace roto.
                    continue
                if documento not in cache_anclas:
                    cache_anclas[documento] = anclas_documento(documento)
                if fragmento not in cache_anclas[documento]:
                    rotos.append(
                        f"{documento.relative_to(RAIZ)}:{linea}: ancla inexistente {destino}"
                    )
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destino) or destino.startswith("//"):
                continue
            if "{{" in destino or "${" in destino:
                continue

            ruta, _, fragmento = destino.partition("#")
            ruta = unquote(ruta.split("?", 1)[0])
            comprobados += 1
            absoluto = ruta.startswith("/")
            ruta_relativa = Path(unquote(ruta))

            if absoluto and ruta_relativa.suffix:
                objetivo = RAIZ / ruta_relativa.relative_to("/")
            elif absoluto:
                if ruta.startswith("/static/"):
                    objetivo = RAIZ / "app" / "static" / ruta_relativa.relative_to("/static")
                elif ruta.startswith("/onboarding/"):
                    objetivo = RAIZ / "docs" / "onboarding-demo" / ruta_relativa.relative_to("/onboarding")
                elif ruta_coincide(ruta, rutas_app):
                    objetivo = None
                else:
                    objetivo = RAIZ / ruta_relativa.relative_to("/")
                    if not objetivo.exists():
                        rotos.append(
                            f"{documento.relative_to(RAIZ)}:{linea}: ruta inexistente {destino}"
                        )
                        continue
            else:
                objetivo = (documento.parent / ruta_relativa).resolve()

            if objetivo is not None:
                try:
                    objetivo.relative_to(RAIZ)
                except ValueError:
                    rotos.append(
                        f"{documento.relative_to(RAIZ)}:{linea}: sale del repositorio {destino}"
                    )
                    continue
                if not objetivo.exists():
                    rotos.append(
                        f"{documento.relative_to(RAIZ)}:{linea}: fichero inexistente {destino}"
                    )
                    continue
                if fragmento and objetivo.suffix.lower() == ".md":
                    if objetivo not in cache_anclas:
                        cache_anclas[objetivo] = anclas_documento(objetivo)
                    if unquote(fragmento) not in cache_anclas[objetivo]:
                        rotos.append(
                            f"{documento.relative_to(RAIZ)}:{linea}: ancla inexistente {destino}"
                        )
    return rotos, comprobados


def recuento_openapi() -> dict[str, int]:
    """Calcula recuentos reproducibles del esquema OpenAPI."""
    from app.main import app

    esquema = app.openapi()
    paths = esquema.get("paths", {})
    api = [ruta for ruta in paths if ruta.startswith("/api/")]
    main = [ruta for ruta in paths if not ruta.startswith("/api/")]
    get_rutas = [ruta for ruta, ops in paths.items() if "get" in ops]
    get_api = [ruta for ruta in get_rutas if ruta.startswith("/api/")]
    get_main = [ruta for ruta in get_rutas if not ruta.startswith("/api/")]
    operaciones = sum(len(ops) for ops in paths.values())
    operaciones_api = sum(
        len(ops) for ruta, ops in paths.items() if ruta.startswith("/api/")
    )
    operaciones_main = operaciones - operaciones_api
    return {
        "paths": len(paths),
        "api_paths": len(api),
        "main_paths": len(main),
        "get_paths": len(get_rutas),
        "get_api_paths": len(get_api),
        "get_main_paths": len(get_main),
        "operations": operaciones,
        "operations_api_paths": operaciones_api,
        "operations_main_paths": operaciones_main,
    }


def rutas_get_main() -> list[str]:
    """Lista las rutas GET no-API publicadas por OpenAPI."""
    from app.main import app

    paths = app.openapi().get("paths", {})
    return sorted(
        ruta for ruta, ops in paths.items()
        if "get" in ops and not ruta.startswith("/api/")
    )


def normalizar_url_app(url: str) -> str:
    """Normaliza una URL de template para compararla con FastAPI."""
    url = unquote(url.split("#", 1)[0].split("?", 1)[0])
    url = re.sub(r"\{%.*?%\}", "", url)
    url = re.sub(r"\{\{.*?\}\}", "1", url)
    url = re.sub(r"\$\{.*?\}", "1", url)
    return url


def referencia_existe(url: str, rutas: set[str]) -> bool:
    """Indica si una URL local apunta a una ruta o fichero real."""
    url = normalizar_url_app(url)
    if not url.startswith("/"):
        return False
    if url.startswith("/static/"):
        return (RAIZ / "app" / "static" / url.removeprefix("/static/")).exists()
    return ruta_coincide(url, rutas)


def recuento_referencias() -> dict[str, int]:
    """Cuenta URLs locales únicas en templates y JavaScript."""
    urls_templates: set[str] = set()
    plantillas = list((RAIZ / "app" / "templates").rglob("*.html"))
    for plantilla in plantillas:
        texto = plantilla.read_text(encoding="utf-8", errors="replace")
        urls_templates.update(
            url for url in TEMPLATE_ATTR_RE.findall(texto)
            if url.startswith("/") and not url.startswith("//")
        )

    urls_js: set[str] = set()
    for archivo_js in (RAIZ / "app" / "static" / "js").rglob("*.js"):
        texto = archivo_js.read_text(encoding="utf-8", errors="replace")
        urls_js.update(
            url for url in JS_URL_RE.findall(texto) if url.startswith("/api/")
        )

    rutas = cargar_rutas_app()
    templates_sin_match = sorted(
        url for url in urls_templates if not referencia_existe(url, rutas)
    )
    js_sin_match = sorted(url for url in urls_js if not referencia_existe(url, rutas))
    return {
        "templates": len(plantillas),
        "template_urls": len(urls_templates),
        "template_urls_match": len(urls_templates) - len(templates_sin_match),
        "template_urls_no_match": len(templates_sin_match),
        "js_urls": len(urls_js),
        "js_urls_match": len(urls_js) - len(js_sin_match),
        "js_urls_no_match": len(js_sin_match),
    }


def referencias_sin_match() -> tuple[list[str], list[str]]:
    """Devuelve las URLs de template y JS que no existen."""
    rutas = cargar_rutas_app()
    urls_templates: set[str] = set()
    for plantilla in (RAIZ / "app" / "templates").rglob("*.html"):
        texto = plantilla.read_text(encoding="utf-8", errors="replace")
        urls_templates.update(
            url for url in TEMPLATE_ATTR_RE.findall(texto)
            if url.startswith("/") and not url.startswith("//")
        )
    urls_js: set[str] = set()
    for archivo_js in (RAIZ / "app" / "static" / "js").rglob("*.js"):
        texto = archivo_js.read_text(encoding="utf-8", errors="replace")
        urls_js.update(
            url for url in JS_URL_RE.findall(texto) if url.startswith("/api/")
        )
    return (
        sorted(url for url in urls_templates if not referencia_existe(url, rutas)),
        sorted(url for url in urls_js if not referencia_existe(url, rutas)),
    )


def comprobar_rutas_readme() -> tuple[list[str], int]:
    """Contrasta la tabla de endpoints de README con OpenAPI y app.routes."""
    from app.main import app

    esquema = app.openapi().get("paths", {})
    rutas_app = {getattr(ruta, "path", "") for ruta in app.routes}
    texto = (RAIZ / "README.md").read_text(encoding="utf-8", errors="replace")
    coincidencias = re.findall(
        r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`",
        texto,
        flags=re.M | re.I,
    )
    rotos: list[str] = []
    for metodo, ruta in coincidencias:
        operaciones = esquema.get(ruta)
        if operaciones is None:
            if ruta not in rutas_app:
                rotos.append(f"{metodo.upper()} {ruta}: ruta inexistente")
            continue
        if metodo.lower() not in operaciones:
            rotos.append(f"{metodo.upper()} {ruta}: metodo no publicado")
    return rotos, len(coincidencias)


def main() -> int:
    if "--counts" in sys.argv:
        print("OPENAPI=" + repr(recuento_openapi()))
        print("REFERENCIAS=" + repr(recuento_referencias()))
        print("GET_MAIN=" + repr(rutas_get_main()))
        templates_sin_match, js_sin_match = referencias_sin_match()
        print("TEMPLATES_SIN_MATCH=" + repr(templates_sin_match))
        print("JS_SIN_MATCH=" + repr(js_sin_match))

    rutas_readme_rotas, rutas_readme_total = comprobar_rutas_readme()
    for detalle in rutas_readme_rotas:
        print("ROTO_README " + detalle)
    print(f"RUTAS_README_COMPROBADAS={rutas_readme_total}")
    print(f"RUTAS_README_ROTAS={len(rutas_readme_rotas)}")

    rotos, comprobados = comprobar_enlaces()
    for detalle in rotos:
        print("ROTO " + detalle)
    print(f"ENLACES_COMPROBADOS={comprobados}")
    print(f"ENLACES_ROTOS={len(rotos)}")
    return 1 if rotos else 0


if __name__ == "__main__":
    raise SystemExit(main())
