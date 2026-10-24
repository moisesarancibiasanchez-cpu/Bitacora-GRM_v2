"""
Catálogo único del LOV de ``Ticket.resultado_pruebas``.

Este módulo es la **única fuente de verdad** para:

  * los valores canónicos del LOV (``RESULTADOS_LOV``),
  * el acrónimo corto que se muestra en las tarjetas del Kanban
    (``ACRONIMOS``),
  * la paleta de color asociada a cada valor (``COLORES``),
  * la normalización de variantes heredadas de la migración UAT
    (``normalizar_resultado``),
  * el lookup que consumen las plantillas y el dashboard
    (``info_resultado``).

Por qué centralizarlo
---------------------
Antes de este módulo la paleta existía duplicada en dos lugares y con
valores **distintos**:

  * ``app/templates/dashboard/index.html`` → ``CUENTA_RESULTADO_COLORES``
    (paleta viva, la que usa el loader ``cargarCuentaResultado()``),
  * ``app/templates/dashboard/index.html`` → ``RESULTADO_COLORS``
    (paleta muerta dentro de ``renderCuentaResultado()``, que nunca se
    invoca y usaba tonos Tailwind en lugar de los del dashboard).

Esa duplicación hacía imposible garantizar el requisito de negocio
"el indicador de las tarjetas y el título de la sección *Cuenta de
Resultado* deben usar los mismos colores". Con este módulo:

  * las tarjetas Jinja usan ``resultado_info(...)`` (global del entorno),
  * el dashboard recibe la paleta serializada desde Python
    (``paleta_js()``) y la usa tal cual, sin redeclarar colores.

Ambos caminos consumen, por construcción, la misma paleta.

Acrónimos (mapeo 1:1 con las 6 categorías solicitadas)
-------------------------------------------------------
===================  =========  =========================
Valor del LOV        Acrónimo   Categoría solicitada
===================  =========  =========================
``OK``               ``OK``     OK
``N/A``              ``N/A``    N/A
``OK CON OBS.``      ``OBS``    OBS
``POSTERGADA``       ``POST``   POST
``DESESTIMADA``      ``NOOK``   NOOK
``NOK``              ``NOK``    NOK
===================  =========  =========================

``(en blanco)`` es la pseudo-columna que agrupa tickets con
``resultado_pruebas`` NULL o vacío en la tabla pivote del dashboard; su
acrónimo es ``S/D`` (sin dato).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from markupsafe import Markup, escape

# ---------------------------------------------------------------------------
# Valores canónicos del LOV
# ---------------------------------------------------------------------------

#: Valores reales de ``Ticket.resultado_pruebas`` (columna ``VARCHAR(40)``).
#: El orden es el mismo que usa el pivote "Cuenta de Resultado".
RESULTADOS_LOV: tuple = (
    "N/A",
    "NOK",
    "OK",
    "OK CON OBS.",
    "POSTERGADA",
    "DESESTIMADA",
)

#: Pseudo-columna del dashboard que agrupa NULL / vacío / desconocidos.
SIN_RESULTADO = "(en blanco)"

#: Todas las claves conocidas por el catálogo (LOV + pseudo-columna).
RESULTADOS_CONOCIDOS: tuple = RESULTADOS_LOV + (SIN_RESULTADO,)


# ---------------------------------------------------------------------------
# Acrónimos
# ---------------------------------------------------------------------------

ACRONIMOS: Dict[str, str] = {
    "OK": "OK",
    "N/A": "N/A",
    "OK CON OBS.": "OBS",
    "POSTERGADA": "POST",
    "DESESTIMADA": "NOOK",
    "NOK": "NOK",
    SIN_RESULTADO: "S/D",
}


# ---------------------------------------------------------------------------
# Paleta de colores
# ---------------------------------------------------------------------------

#: Paleta canónica. Copia **exacta** de la que ya usaba el loader vivo
#: ``cargarCuentaResultado()`` del dashboard (``CUENTA_RESULTADO_COLORES``),
#: para no alterar la apariencia actual del reporte.
#:
#: * ``bg``        → fondo sólido (encabezado de columna / badge de tarjeta)
#: * ``text``      → color de texto sobre el fondo sólido
#: * ``cellText`` → color de texto de los números sobre fondo tenue
COLORES: Dict[str, Dict[str, str]] = {
    "N/A":         {"bg": "#94a3b8", "text": "#ffffff", "cellText": "#1f2937"},
    "NOK":         {"bg": "#dc2626", "text": "#ffffff", "cellText": "#1f2937"},
    "OK":          {"bg": "#16a34a", "text": "#ffffff", "cellText": "#1f2937"},
    "OK CON OBS.": {"bg": "#eab308", "text": "#1f2937", "cellText": "#1f2937"},
    "POSTERGADA":  {"bg": "#ea580c", "text": "#ffffff", "cellText": "#1f2937"},
    "DESESTIMADA": {"bg": "#7c3aed", "text": "#ffffff", "cellText": "#1f2937"},
    SIN_RESULTADO: {"bg": "#cbd5e1", "text": "#475569", "cellText": "#1f2937"},
}

#: Color de respaldo cuando la columna no está en el catálogo.
COLOR_FALLBACK: Dict[str, str] = {
    "bg": "#475569",
    "text": "#ffffff",
    "cellText": "#1f2937",
}


# ---------------------------------------------------------------------------
# Normalización de variantes heredadas (mismas tolerancias que el pivot SQL)
# ---------------------------------------------------------------------------

_ALIASES: Dict[str, str] = {
    "n/a": "N/A",
    "na": "N/A",
    "no aplica": "N/A",
    "no aplica ": "N/A",
    "nok": "NOK",
    "ok": "OK",
    "ok con obs.": "OK CON OBS.",
    "ok con obs": "OK CON OBS.",
    "ok con obs.": "OK CON OBS.",
    "ok con observaciones": "OK CON OBS.",
    "ok con observación": "OK CON OBS.",
    "ok con observacion": "OK CON OBS.",
    "ok con observ.": "OK CON OBS.",
    "ok c/obs": "OK CON OBS.",
    "ok cobs": "OK CON OBS.",
    "postergada": "POSTERGADA",
    "postergada a garantía": "POSTERGADA",
    "postergada a garantia": "POSTERGADA",
    "postergado": "POSTERGADA",
    "desestimada": "DESESTIMADA",
    "desestimado": "DESESTIMADA",
    "(en blanco)": SIN_RESULTADO,
    "": SIN_RESULTADO,
}


def normalizar_resultado(valor: Any) -> Optional[str]:
    """Normaliza cualquier variante de entrada a un valor canónico del catálogo.

    Devuelve ``None`` cuando el valor está vacío o no corresponde a ningún
    valor del LOV (en ese caso el llamador decide si usa la pseudo-columna
    ``(en blanco)`` o no muestra nada).

    >>> normalizar_resultado("  ok con observacion ")
    'OK CON OBS.'
    >>> normalizar_resultado("POSTERGADO")
    'POSTERGADA'
    >>> normalizar_resultado("xyz") is None
    True
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    # Coincidencia exacta (case-sensitive) con un valor canónico.
    if texto in COLORES:
        return texto
    clave = texto.lower().rstrip()
    if clave in _ALIASES:
        canonico = _ALIASES[clave]
        return None if canonico == SIN_RESULTADO else canonico
    # Último recurso: coincidencia sin<tildes/no-puntos.
    compacto = clave.replace(".", "").replace(" ", "")
    for alias, canonico in _ALIASES.items():
        if canonico == SIN_RESULTADO:
            continue
        if alias.replace(".", "").replace(" ", "") == compacto:
            return canonico
    return None


def info_resultado(valor: Any) -> Optional[Dict[str, Any]]:
    """Devuelve la ficha completa (valor, acrónimo, colores) de un resultado.

    >>> info_resultado("OK CON OBS.")["acronimo"]
    'OBS'
    >>> info_resultado("") is None
    True
    """
    canonico = normalizar_resultado(valor)
    if canonico is None:
        return None
    color = COLORES.get(canonico, COLOR_FALLBACK)
    return {
        "valor": canonico,
        "acronimo": ACRONIMOS.get(canonico, canonico),
        "bg": color["bg"],
        "text": color["text"],
        "cellText": color["cellText"],
        "titulo": "Resultado de pruebas: {0}".format(canonico),
    }


#: Tipos de ticket para los que el campo ``resultado_pruebas`` es
#: aplicable (y por lo tanto se muestra el badge "S/D" cuando está vacío).
_TIPOS_CON_RESULTADO = ("incidencia", "resultado_pruebas")

#: Estilo neutro para valores fuera del LOV (no se pierde en silencio).
_ESTILO_DESCONOCIDO: Dict[str, str] = {
    "bg": "#e2e8f0",
    "text": "#334155",
    "cellText": "#1f2937",
}


def _tipo_ticket(ticket: Any) -> str:
    """Extrae el tipo del ticket como texto plano y en minúsculas."""
    tipo = getattr(ticket, "tipo", None)
    if tipo is None:
        return ""
    # ``tipo`` es un Enum (TipoIncidencia) o un string suelto.
    return str(getattr(tipo, "value", tipo)).strip().lower()


def info_resultado_ticket(ticket: Any) -> Optional[Dict[str, Any]]:
    """Ficha del resultado de pruebas de un ticket, lista para pintar.

    Reglas:

    * Valor reconocido en el LOV → ficha canónica (color + acrónimo).
    * Valor vacío → ficha ``(en blanco)`` (acrónimo ``S/D``) **sólo** si el
      tipo de ticket es aplicable; en otro caso devuelve ``None`` y la
      tarjeta no muestra badge (para no ensuciar solicitudes/cambios).
    * Valor no vacío fuera del LOV → ficha neutra con el texto crudo, de
      modo que un dato mal capturado sea visible y no desaparezca.
    """
    valor = getattr(ticket, "resultado_pruebas", None)
    ficha = info_resultado(valor)
    if ficha is not None:
        return ficha

    texto = "" if valor is None else str(valor).strip()
    if not texto:
        if _tipo_ticket(ticket) not in _TIPOS_CON_RESULTADO:
            return None
        color = COLORES[SIN_RESULTADO]
        return {
            "valor": SIN_RESULTADO,
            "acronimo": ACRONIMOS[SIN_RESULTADO],
            "bg": color["bg"],
            "text": color["text"],
            "cellText": color["cellText"],
            "titulo": "Resultado de pruebas: sin dato",
        }

    # Valor fuera del LOV: se muestra neutro para que quede visible.
    return {
        "valor": texto,
        "acronimo": texto[:10].upper(),
        "bg": _ESTILO_DESCONOCIDO["bg"],
        "text": _ESTILO_DESCONOCIDO["text"],
        "cellText": _ESTILO_DESCONOCIDO["cellText"],
        "titulo": "Resultado de pruebas (fuera del LOV): {0}".format(texto),
    }


def paleta_js() -> Dict[str, Dict[str, str]]:
    """Paleta serializable para inyectar en el dashboard.

    Se entrega con ``|tojson`` desde el contexto del template para que el
    JavaScript del dashboard consuma **la misma** paleta que las tarjetas
    (sin volver a declararla a mano).
    """
    return {clave: dict(valores) for clave, valores in COLORES.items()}


def acronimos_js() -> Dict[str, str]:
    """Mapa ``valor → acrónimo`` serializable para el dashboard."""
    return dict(ACRONIMOS)


# ---------------------------------------------------------------------------
# Render del badge (compartido por los 3 renderizadores de tarjeta)
# ---------------------------------------------------------------------------

#: Plantilla del badge. Se define **una sola vez** aquí para que
#: ``tarjeta.html``, ``card.py`` y ``tarjeta.py`` produzcan markup idéntico.
_BADGE_TEMPLATE = (
    '<span class="inline-flex items-center rounded px-1.5 py-[1px] text-[10px] '
    'font-bold uppercase leading-none tracking-wide shrink-0" '
    'style="background-color:{bg};color:{text};" '
    'title="{titulo}" data-resultado-pruebas="{valor}">{acronimo}</span>'
)


def render_badge_resultado(ficha: Optional[Dict[str, Any]]) -> str:
    """Renderiza el badge del indicador de *Resultado de Pruebas*.

    Recibe la ficha devuelta por :func:`info_resultado_ticket` (o ``None``)
    y devuelve el HTML del badge (cadena vacía si no hay nada que mostrar).

    Devuelve un objeto ``Markup`` para que Jinja **no** lo escape al
    insertarlo con ``{{ ... }}`` en una plantilla con autoescape activo.
    """
    if not ficha:
        return Markup("")
    try:
        return Markup(
            _BADGE_TEMPLATE.format(
                bg=escape(ficha["bg"]),
                text=escape(ficha["text"]),
                titulo=escape(ficha["titulo"]),
                valor=escape(ficha["valor"]),
                acronimo=escape(ficha["acronimo"]),
            )
        )
    except (KeyError, TypeError, ValueError):
        # Nunca romper el render de una tarjeta por un dato raro.
        return Markup("")

