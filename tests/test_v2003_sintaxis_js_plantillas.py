"""Regresion de V2.003: sintaxis JavaScript de las plantillas del proyecto.

Contexto del defecto
--------------------
El despliegue del lote V2.002 dejo el dashboard en blanco: la pagina se
servia (HTTP 200) pero se quedaba eternamente en "Cargando metricas...".

Causa raiz: un error de sintaxis JavaScript en el bloque <script> inline de
``app/templates/dashboard/index.html``. En la funcion ``_renderModalKpiDetalle``
el ternario que muestra el aviso de truncamiento quedo escrito asi:

    +       (data.truncado
    +         ? '<p ...>Se muestran '
    +         : '')

Los signos "+" de las lineas de continuacion del ternario son operadores de
concatenacion, pero dentro de un ternario no tienen sentido: el parser los
interpreta como ``data.truncado + ?``, y el navegador rechaza el bloque
completo con::

    SyntaxError: Unexpected token '?'

Como el error estaba en el unico bloque <script> de la pagina, NADA del
dashboard se ejecutaba: ni las tarjetas de KPI, ni la tabla de incidencias,
ni el modal de drill-down.

Por que no lo detecto la suite de V2.002
-----------------------------------------
La suite de V2.002 verificaba el COMPORTAMIENTO del modal leyendo el HTML de
la plantilla con expresiones regulares y el HTML renderizado por el cliente
HTTP de pruebas. Ninguna de las dos cosas ejecuta JavaScript, asi que un error
de sintaxis puro es invisible para ellas: el HTML se sirve igual y las pruebas
pasaban mientras el dashboard estaba roto en produccion.

Que fija esta suite
-------------------
Un validador de sintaxis JavaScript (lexico propio, sin dependencias
nuevas) que se aplica a:

  * todos los bloques <script> inline de ``app/templates/**/*.html``;
  * todos los ficheros ``.js`` propios de ``app/static/js`` (excluidos los
    ``*.min.js`` de terceros).

El validador comprueba, ademas de la terminacion de cadenas, plantillas,
comentarios y expresiones regulares y del balance de delimitadores, la regla
que hizo fallar al dashboard: **un operador binario no puede ir seguido de un
token que no pueda iniciar una expresion** (por ejemplo ``+ ?`` o ``+ :``).

Ademas la suite incluye un test de autocomprobacion: si el validador dejara
de detectar el defecto original, el test falla. Asi el fichero no puede
quedarse vacio de contenido sin que nadie se entere.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest  # noqa: F401  (mantiene la convencion de imports de la suite)
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
DIR_TEMPLATES = RAIZ / "app" / "templates"
DIR_JS = RAIZ / "app" / "static" / "js"
PLANTILLA_DASHBOARD = DIR_TEMPLATES / "dashboard" / "index.html"

CLAVE = "Clave-local-de-regresion-2026"


# ===========================================================================
# Lexico de JavaScript (sin dependencias externas)
# ===========================================================================

KEYWORDS_NO_INICIO = {
    "else", "case", "catch", "finally", "in", "of", "instanceof", "return",
    "throw", "do", "while", "for", "if", "switch", "break", "continue",
    "var", "let", "const", "default", "extends", "implements", "package",
    "private", "protected", "public", "static",
}

EXPR_START_PUNCT = {"(", "[", "{", "!", "~", "+", "-", "++", "--"}
EXPR_END_PUNCT = {")", "]", "}", "++", "--"}
EXPR_END_WORDS = {"this", "super", "true", "false", "null", "undefined"}

BINARIOS = {
    "+", "-", "*", "/", "%", "**", "&", "|", "^", "&&", "||", "??",
    "==", "!=", "===", "!==", "<", ">", "<=", ">=", "<<", ">>", ">>>",
}

MULTI = [
    ">>>=", "...", "===", "!==", "**=", "<<=", ">>=", ">>>", "&&=", "||=",
    "??=", "=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "**",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "++", "--",
]

IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
NUM_RE = re.compile(r"(?:0[xXbBoO][0-9a-fA-F_]+|(?:\d[\d_]*)?\.?\d[\d_]*(?:[eE][+-]?\d+)?)n?")
RE_SCRIPT = re.compile(r"<script(?P<attrs>[^>]*)>", re.IGNORECASE)


class Problema:
    """Defecto de sintaxis detectado en un bloque de JavaScript."""

    def __init__(self, fichero: str, linea: int, mensaje: str):
        self.fichero = fichero
        self.linea = linea
        self.mensaje = mensaje

    def __str__(self) -> str:
        return "%s linea %d: %s" % (self.fichero, self.linea, self.mensaje)


def _puede_terminar(tok) -> bool:
    if tok is None:
        return False
    tipo, valor, _pos = tok
    if tipo == "code":
        return valor not in KEYWORDS_NO_INICIO or valor in EXPR_END_WORDS
    if tipo in ("string", "template", "regex", "num"):
        return True
    if tipo == "punct":
        return valor in EXPR_END_PUNCT
    return False


def _puede_iniciar(tok) -> bool:
    """True si el token puede iniciar una expresion."""
    if tok is None:
        return False
    tipo, valor, _pos = tok
    if tipo in ("string", "template", "regex", "num"):
        return True
    if tipo == "punct":
        return valor in EXPR_START_PUNCT
    if tipo == "code":
        return valor not in KEYWORDS_NO_INICIO
    return False


def _lex(fichero: str, codigo: str, problemas: list) -> list:
    """Tokeniza codigo JavaScript y devuelve los tokens significativos."""
    tokens = []
    pila = []
    pares = {")": "(", "]": "[", "}": "{"}
    i = 0
    n = len(codigo)
    linea = 1
    ultimo = None

    def anota(tok):
        nonlocal ultimo
        tokens.append(tok)
        ultimo = tok

    while i < n:
        c = codigo[i]
        if c == "\n":
            linea += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue

        # Comentarios
        if c == "/" and i + 1 < n and codigo[i + 1] == "/":
            j = codigo.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and codigo[i + 1] == "*":
            j = codigo.find("*/", i + 2)
            if j == -1:
                problemas.append(Problema(fichero, linea, "comentario de bloque sin cerrar"))
                break
            linea += codigo.count("\n", i, j)
            i = j + 2
            continue

        # Cadenas
        if c in ("'", '"'):
            comilla = c
            j = i + 1
            cerrado = False
            while j < n:
                d = codigo[j]
                if d == "\\":
                    if j + 1 < n and codigo[j + 1] == "\n":
                        linea += 1
                    j += 2
                    continue
                if d == "\n":
                    break
                if d == comilla:
                    j += 1
                    cerrado = True
                    break
                j += 1
            if not cerrado:
                problemas.append(Problema(fichero, linea, "cadena sin cerrar (%s)" % comilla))
                break
            anota(("string", codigo[i:j], i))
            i = j
            continue

        # Plantillas (template literals)
        if c == "`":
            j, prof, cerrado = i + 1, 0, False
            while j < n:
                d = codigo[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "$" and j + 1 < n and codigo[j + 1] == "{":
                    prof += 1
                    j += 2
                    continue
                if d == "}" and prof > 0:
                    prof -= 1
                    j += 1
                    continue
                if d == "`" and prof == 0:
                    j += 1
                    cerrado = True
                    break
                if d == "\n":
                    linea += 1
                j += 1
            if not cerrado:
                problemas.append(Problema(fichero, linea, "plantilla sin cerrar"))
                break
            anota(("template", codigo[i:j], i))
            i = j
            continue

        # Expresiones regulares (solo donde no puede ser una division)
        if c == "/" and not _puede_terminar(ultimo):
            j = i + 1
            en_clase = False
            cerrado = False
            while j < n:
                d = codigo[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "[":
                    en_clase = True
                elif d == "]":
                    en_clase = False
                elif d == "/" and not en_clase:
                    j += 1
                    cerrado = True
                    break
                elif d == "\n":
                    break
                j += 1
            if not cerrado:
                problemas.append(Problema(fichero, linea, "expresion regular sin cerrar"))
                break
            while j < n and codigo[j] in "gimsuyd":
                j += 1
            anota(("regex", codigo[i:j], i))
            i = j
            continue

        # Identificadores y numeros
        if c.isalpha() or c in "_$":
            m = IDENT_RE.match(codigo, i)
            anota(("code", m.group(0), i))
            i = m.end()
            continue
        if c.isdigit() or (c == "." and i + 1 < n and codigo[i + 1].isdigit()):
            m = NUM_RE.match(codigo, i)
            anota(("num", m.group(0), i))
            i = m.end()
            continue

        # Operadores de dos o mas caracteres
        emparejado = None
        for op in MULTI:
            if codigo.startswith(op, i):
                emparejado = op
                break
        if emparejado == "?." and codigo[i + 2:i + 3].isdigit():
            emparejado = None
        if emparejado:
            anota(("punct", emparejado, i))
            i += len(emparejado)
            continue

        # Puntuacion
        if c in "([{":
            pila.append((c, linea))
        elif c in ")]}":
            if not pila:
                problemas.append(Problema(fichero, linea, "cierre sobrante '%s'" % c))
            else:
                op, ol = pila.pop()
                if op != pares[c]:
                    problemas.append(Problema(
                        fichero, linea,
                        "se cierra '%s' pero se abrio '%s' (linea %d)" % (c, op, ol)))
        anota(("punct", c, i))
        i += 1

    for op, ol in pila:
        problemas.append(Problema(fichero, ol, "delimitador '%s' sin cerrar" % op))

    return tokens


def valida_js(fichero: str, codigo: str) -> list:
    """Devuelve la lista de defectos de sintaxis detectados en el codigo JS."""
    problemas: list = []
    tokens = _lex(fichero, codigo, problemas)

    for idx, tok in enumerate(tokens):
        tipo, valor, pos = tok
        if tipo != "punct":
            continue
        siguiente = tokens[idx + 1] if idx + 1 < len(tokens) else None
        if valor in BINARIOS:
            if not _puede_iniciar(siguiente):
                problemas.append(Problema(
                    fichero, codigo.count("\n", 0, pos) + 1,
                    "el operador '%s' va seguido de un token que no puede iniciar una "
                    "expresion (SyntaxError: Unexpected token)" % valor))
        elif valor == "?":
            if not _puede_iniciar(siguiente):
                problemas.append(Problema(
                    fichero, codigo.count("\n", 0, pos) + 1,
                    "el '?' ternario va seguido de un token que no puede iniciar una "
                    "expresion (SyntaxError: Unexpected token '?')"))

    vistos = set()
    unicos = []
    for p in problemas:
        clave = (p.fichero, p.linea, p.mensaje)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(p)
    return unicos


def extrae_scripts(html: str) -> list:
    """Devuelve [(linea_inicio, codigo)] de cada bloque <script> de JavaScript.

    Se ignoran los <script src=...> (el codigo esta en un fichero externo) y
    los que declaran un tipo que no es JavaScript (por ejemplo
    type="application/json").
    """
    bloques = []
    lineas = html.split("\n")
    i = 0
    while i < len(lineas):
        s = lineas[i].strip()
        m = RE_SCRIPT.match(s)
        if m:
            attrs = m.group("attrs")
            if re.search(r"\bsrc\s*=", attrs, re.IGNORECASE):
                i += 1
                continue
            tipo = re.search(r'type\s*=\s*["\']?([^"\'\s>]+)', attrs, re.IGNORECASE)
            es_js = True
            if tipo:
                es_js = tipo.group(1).lower() in (
                    "", "text/javascript", "application/javascript",
                    "module", "text/ecmascript", "application/ecmascript",
                )
            if es_js:
                inicio = i + 1
                codigo = []
                resto = s[m.end():]
                if resto.strip():
                    codigo.append(resto)
                j = i + 1
                while j < len(lineas):
                    if "</script>" in lineas[j]:
                        cola = lineas[j].split("</script>")[0]
                        if cola.strip():
                            codigo.append(cola)
                        break
                    codigo.append(lineas[j])
                    j += 1
                bloques.append((inicio, "\n".join(codigo)))
                i = j + 1
                continue
        i += 1
    return bloques


def _ficheros_plantillas():
    return sorted(p for p in DIR_TEMPLATES.rglob("*.html"))


def _ficheros_js_propios():
    return sorted(p for p in DIR_JS.glob("*.js") if not p.name.endswith(".min.js"))


# ===========================================================================
# Tests
# ===========================================================================
def test_el_validador_detecta_el_defecto_original():
    """Autocomprobacion: el validador tiene que ver el defecto de V2.002.

    Si este test falla, el validador se ha quedado sin dientes y el resto de
    la suite pasaria aunque el dashboard volviera a estar roto.
    """
    defectuoso = (
        "var html = ''\n"
        "      +       (data.truncado\n"
        "      +         ? '<p>Se muestran '\n"
        "      +         : '')\n"
    )
    problemas = valida_js("defectuoso.js", defectuoso)
    assert problemas, "el validador NO detecta el defecto original de V2.002"
    assert any("Unexpected token" in p.mensaje for p in problemas)

    # Y el mismo codigo ya corregido no debe dar problemas.
    correcto = (
        "var html = ''\n"
        "      +       (data.truncado\n"
        "        ? '<p>Se muestran '\n"
        "        : '')\n"
    )
    assert valida_js("correcto.js", correcto) == []


def test_ninguna_plantilla_tiene_defectos_de_sintaxis_js():
    """Todos los bloques <script> inline de las plantillas deben ser validos."""
    hallazgos = []
    for ruta in _ficheros_plantillas():
        html = io.open(ruta, "r", encoding="utf-8", errors="replace").read()
        for inicio, codigo in extrae_scripts(html):
            for p in valida_js("%s (bloque en linea %d)" % (ruta.name, inicio), codigo):
                hallazgos.append(str(p))
    assert not hallazgos, (
        "se han detectado defectos de sintaxis JavaScript en las plantillas:\n  - "
        + "\n  - ".join(hallazgos)
    )


def test_los_ficheros_js_propios_no_tienen_defectos_de_sintaxis():
    """Los ficheros .js del proyecto (sin los minificados de terceros)."""
    hallazgos = []
    for ruta in _ficheros_js_propios():
        codigo = io.open(ruta, "r", encoding="utf-8", errors="replace").read()
        for p in valida_js(ruta.name, codigo):
            hallazgos.append(str(p))
    assert not hallazgos, (
        "se han detectado defectos de sintaxis JavaScript en los ficheros .js:\n  - "
        + "\n  - ".join(hallazgos)
    )


def test_dashboard_sin_concatenacion_rota_de_ternario():
    """Ninguna linea del script del dashboard puede empezar por '+ ?' o '+ :'.

    Esta es la forma exacta del defecto de V2.002: un signo '+' de
    concatenacion en una linea de continuacion de un ternario.
    """
    html = io.open(PLANTILLA_DASHBOARD, "r", encoding="utf-8", errors="replace").read()
    sospechosos = []
    for numero, linea in enumerate(html.split("\n"), start=1):
        if re.match(r"^\s*\+\s*[?:]\s", linea):
            sospechosos.append("linea %d: %s" % (numero, linea.strip()))
    assert not sospechosos, (
        "el dashboard contiene una concatenacion rota de ternario:\n  - "
        + "\n  - ".join(sospechosos)
    )


def test_el_html_renderizado_del_dashboard_pasa_el_validador():
    """El HTML que sirve la aplicacion tambien tiene que ser valido.

    A diferencia de leer la plantilla en crudo, esto comprueba el resultado
    final: lo que el navegador recibe y ejecuta.
    """
    from app.core.security import hash_password
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.main import app
    from app.models.usuario import RolUsuario, Usuario

    Base.metadata.create_all(bind=engine)

    usuario = "v2003_admin_js"
    sesion = SessionLocal()
    try:
        if sesion.query(Usuario).filter(Usuario.username == usuario).first() is None:
            sesion.add(Usuario(
                username=usuario,
                email="%s@example.test" % usuario,
                nombre_completo="Admin V2003",
                hashed_password=hash_password(CLAVE),
                rol=RolUsuario.ADMINISTRADOR,
                is_active=True,
            ))
            sesion.commit()
    finally:
        sesion.close()

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": usuario, "password": CLAVE},
        )
        assert login.status_code == 200, login.text

        respuesta = client.get("/dashboard")
        assert respuesta.status_code == 200, respuesta.text

    html = respuesta.text
    bloques = extrae_scripts(html)
    assert bloques, "el dashboard servido no tiene bloques <script> de JavaScript"

    hallazgos = []
    for inicio, codigo in bloques:
        for p in valida_js("dashboard renderizado (bloque en linea %d)" % inicio, codigo):
            hallazgos.append(str(p))
    assert not hallazgos, (
        "el HTML renderizado del dashboard tiene errores de sintaxis JavaScript:\n  - "
        + "\n  - ".join(hallazgos)
    )
