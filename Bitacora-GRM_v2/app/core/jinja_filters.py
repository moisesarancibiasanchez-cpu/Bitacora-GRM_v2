"""
Filtros personalizados de Jinja2 para plantillas de la Bitácora GRM.

Este módulo expone funciones que se registran en el entorno de Jinja2
para ser usadas dentro de las plantillas HTML. Por ahora contiene:

- ``truncate_text``: limpia y trunca texto markdown (descripciones de
  tickets, comentarios, etc.) a un número máximo de caracteres útil para
  mostrar en tarjetas del Kanban sin romper el diseño.

El objetivo es que la tarjeta Kanban tenga siempre una altura estable,
independientemente del largo del texto que el usuario haya escrito en
el campo "DESCRIPCION DETALLE" (que admite markdown).
"""
from __future__ import annotations

import re

# Caracteres ~70 para la vista de tarjeta Kanban. Es el largo aproximado
# que cabe en dos líneas con el tamaño ``text-xs`` de Tailwind.
DEFAULT_MAX_CHARS = 70

# Patrones de markdown comunes que no aportan valor en una vista de
# tarjeta: encabezados, énfasis, comillas de bloque, links, imágenes,
# código inline, listas y barras horizontales.
_MD_PATTERNS = [
    re.compile(r"^#{1,6}\s*"),               # # ## ### ...
    re.compile(r"\*\*(?P<t>[^*]+)\*\*"),     # **bold**
    re.compile(r"__(?P<t>[^_]+)__"),         # __bold__
    re.compile(r"(?<!\*)\*(?!\*)(?P<t>[^*]+)\*(?!\*)"),  # *italic*
    re.compile(r"(?<!_)_(?!_)(?P<t>[^_]+)_(?!_)"),       # _italic_
    re.compile(r"`(?P<t>[^`]+)`"),           # `code`
    re.compile(r"^\s*[-*+]\s+"),             # - item / * item / + item
    re.compile(r"^\s*\d+\.\s+"),             # 1. item
    re.compile(r"^\s*>\s?"),                 # > quote
    re.compile(r"^\s*---+\s*$"),             # --- horizontal rule
    re.compile(r"^\s*\*\*\*+\s*$"),          # *** horizontal rule
    re.compile(r"!\[(?P<a>[^\]]*)\]\((?P<u>[^)]+)\)"),  # ![alt](url)
    re.compile(r"\[(?P<a>[^\]]+)\]\((?P<u>[^)]+)\)"),    # [txt](url)
    re.compile(r"<[^>]+>"),                  # <html> tags
    re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE),  # | tabla |
    re.compile(r"^\s*[-:| ]+\|\s*$", re.MULTILINE),  # separador tabla
]


def _clean_markdown(text: str) -> str:
    """Elimina sintaxis markdown básica y normaliza espacios/saltos."""
    if not text:
        return ""

    cleaned = text

    # Quitar patrones de markdown (se aplican repetidamente para anidados).
    for _ in range(3):  # pocas iteraciones: cubre la mayoría de casos reales
        prev = cleaned
        for pattern in _MD_PATTERNS:
            if "P<t>" in pattern.pattern:
                cleaned = pattern.sub(lambda m: m.group("t"), cleaned)
            else:
                cleaned = pattern.sub("", cleaned)
        if cleaned == prev:
            break

    # Reemplazar saltos de línea y retornos por espacios.
    cleaned = cleaned.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    cleaned = cleaned.replace("\t", " ")

    # Colapsar espacios múltiples.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Segunda pasada: tras colapsar saltos de línea, algunos marcadores de
    # bloque quedan "inline" (por ej. "Sistema ## Pasos"). Limpiarlos
    # repitiendo los patrones sin requerir inicio de línea.
    inline_patterns = [
        re.compile(r"\s*#{1,6}\s+"),                    # ## encabezado
        re.compile(r"\s*\*\*\*+\s+"),                   # *** separador
        re.compile(r"\s*---+\s+"),                      # --- separador
    ]
    for pattern in inline_patterns:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def truncate_text(value, max_chars: int = DEFAULT_MAX_CHARS, suffix: str = "…") -> str:
    """Trunca un texto a ``max_chars`` caracteres de forma segura.

    - Si ``value`` es ``None`` o vacío, devuelve cadena vacía.
    - Elimina sintaxis markdown básica (encabezados, énfasis, listas, etc.).
    - Colapsa saltos de línea y espacios múltiples.
    - Si el texto limpio supera ``max_chars``, lo corta y agrega ``suffix``.

    Uso en plantilla::

        <p class="text-xs text-slate-500 line-clamp-2">
          {{ ticket.descripcion | truncate_text(70) }}
        </p>
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""

    cleaned = _clean_markdown(value)
    if not cleaned:
        return ""

    if len(cleaned) <= max_chars:
        return cleaned

    # Cortar respetando un límite de palabra si es posible.
    cut = cleaned[:max_chars].rstrip()
    if " " in cut:
        # Buscar el último espacio para no cortar a mitad de palabra.
        last_space = cut.rfind(" ")
        if last_space > max_chars * 0.6:  # solo si no recorta demasiado
            cut = cut[:last_space].rstrip()
    return f"{cut}{suffix}"


# Registro simple para que ``main.py`` pueda iterar y agregar los filtros
# al ``templates.env.filters``.
ALL_FILTERS = {
    "truncate_text": truncate_text,
}
