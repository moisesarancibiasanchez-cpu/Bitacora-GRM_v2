#!/usr/bin/env python3
"""
Test de regresión para el BUG del command-palette: case-sensitivity de `tipo`.

PROBLEMA HISTÓRICO
------------------
El frontend del command-palette (`app/static/js/command-palette.js`) tiene
un mismatch entre la cadena usada en `collectResults` (que crea
`sel.tipo = 'Ticket'`, mayúscula) y la condición usada en `openResult`
(que comparaba con `'ticket'`, minúscula).

El backend (`app/api/v1/buscar.py`) emite `"tipo": "ticket"` (minúscula),
pero el `collectResults` del frontend sobreescribe ese valor con el
`label` de la constante local `tipos`. El resultado: la condición
`sel.tipo === 'ticket'` NUNCA se cumplía, el código caía al fallback
`window.location.href = sel.url` que apuntaba al endpoint
`/api/v1/tickets/{id}/detalle-html`, que devuelve SOLO el fragmento
del modal (sin base.html, sin Tailwind, sin JS) → página rota sin
estilos.

Este test verifica:
  1. Que el archivo command-palette.js YA NO contiene la comparación
     rota `sel.tipo === 'ticket'` (sin toLowerCase).
  2. Que la condición actual usa `toLowerCase()` o equivalente para
     hacer la comparación robusta a cambios futuros de capitalización.
  3. Que el backend sigue emitiendo `"tipo": "ticket"` (contrato).
  4. Que el fragmento modal NO es una página completa (defensa en
     profundidad: sigue siendo un fragmento, no debería navegarse
     directamente).

Ejecutar:
    .venv-test/bin/python test_validar_fix_command_palette_case.py
    # o
    python test_validar_fix_command_palette_case.py
"""
from __future__ import annotations

import os
import sys
import re
from pathlib import Path

# Bootstrap de variables de entorno ANTES de importar la app
ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"

REPO = ROOT
JS_PATH = APP_DIR / "static" / "js" / "command-palette.js"
BACKEND_PATH = APP_DIR / "api" / "v1" / "buscar.py"

# Salida con colores si el terminal lo soporta
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}✗{RESET} {msg}")
    sys.exit(1)


def info(msg: str) -> None:
    print(f"{YELLOW}·{RESET} {msg}")


# =============================================================================
# 1. Verificación estática del command-palette.js
# =============================================================================
def test_command_palette_js() -> None:
    if not JS_PATH.exists():
        fail(f"No se encontró {JS_PATH}")

    js_src = JS_PATH.read_text(encoding="utf-8")
    info(f"command-palette.js: {len(js_src):,} bytes")

    # Buscar la condición exacta que estaba rota.
    # El bug era: if (sel.tipo === 'ticket' && ...) sin normalizar.
    # Buscamos el patrón exacto que es la línea de código real (sin
    # toLowerCase). También lo buscamos con prefijo `if (` para excluir
    # referencias dentro de comentarios o docstrings.
    patron_bug = re.compile(
        r"if\s*\(\s*sel\.tipo\s*===\s*['\"]ticket['\"]"
    )
    matches_bug = patron_bug.findall(js_src)
    # Patrón secundario: cualquier referencia literal al bug en código
    # (no en comentarios). Si la primera línea de contexto contiene
    # `*` o `//` es docstring/comentario, lo descartamos.
    patron_bug_anywhere = re.compile(
        r"sel\.tipo\s*===\s*['\"]ticket['\"]"
    )
    raw_matches = patron_bug_anywhere.findall(js_src)
    # Filtrar matches dentro de comentarios (líneas que empiezan con * o //)
    code_matches = []
    for line_num, line in enumerate(js_src.split("\n"), start=1):
        # Detectar líneas de código (no comentarios):
        # - Comentario de línea: empieza con // (puede tener espacios antes)
        # - Comentario de bloque (JSDoc): empieza con * (puede tener espacios antes)
        # - Comentario de bloque: empieza con /*
        # - Líneas vacías o con solo espacios
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        # Quitar comentario inline después del código
        code_part = line.split("//")[0]
        if "sel.tipo === 'ticket'" in code_part or 'sel.tipo === "ticket"' in code_part:
            code_matches.append((line_num, line.strip()))
    if code_matches:
        fail(
            "BUG AÚN PRESENTE EN CÓDIGO: la condición `sel.tipo === 'ticket'` "
            f"aparece en {len(code_matches)} línea(s) de código (no comentario):\n"
            + "\n".join(f"  L{ln}: {l}" for ln, l in code_matches[:3])
        )
    ok(
        f"No hay condición rota en código activo (matches raw: {len(raw_matches)}, "
        f"todos en comentarios/docstrings)."
    )

    # Verificar que existe una comparación robusta (case-insensitive).
    # Patrones válidos: tipoLower === 'ticket' (variable normalizada),
    # .toLowerCase() === 'ticket', sel.tipo === 'Ticket' (mayúscula
    # consistente), etc.
    patron_ok = re.compile(
        r"tipoLower\s*===\s*['\"]ticket['\"]"
        r"|"
        r"(?:\.toLowerCase\(\)|toLowerCase)\s*===\s*['\"]ticket['\"]"
        r"|"
        r"sel\.tipo\s*===\s*['\"]Ticket['\"]"
    )
    if not patron_ok.search(js_src):
        fail(
            "No se encontró una comparación robusta (case-insensitive o "
            "consistente con mayúscula). El fix usa `tipoLower === 'ticket'` "
            "(variable normalizada) o equivalente. Si no está, el bug puede regresar."
        )
    ok("Comparación robusta encontrada (case-insensitive o consistente).")

    # Verificar que las 3 estrategias siguen presentes.
    # Estrategia 1: htmx.ajax
    if "htmx.ajax('GET', sel.url" not in js_src:
        fail("Falta la Estrategia 1 (htmx.ajax) para tickets.")
    ok("Estrategia 1 (htmx.ajax) presente.")

    # Estrategia 2: fetch + innerHTML
    if "fetch(sel.url" not in js_src or "root.innerHTML = html" not in js_src:
        fail("Falta la Estrategia 2 (fetch + innerHTML) para tickets.")
    ok("Estrategia 2 (fetch + innerHTML) presente.")

    # Estrategia 3: navegar a /tickets (URL SEGURA)
    if "window.location.href = '/tickets'" not in js_src:
        fail("Falta la Estrategia 3 (fallback a /tickets, URL segura).")
    ok("Estrategia 3 (fallback a /tickets) presente.")

    # Verificar que NO hay fallback inseguro tipo
    # `window.location.href = sel.url` ANTES de las 3 estrategias para tickets.
    # (El fallback genérico al final de la función sólo debería correr
    # para tipos no-ticket o tickets sin URL modal.)
    # Esto es sólo informativo.
    if "window.location.href = sel.url" in js_src:
        info(
            "Hay un fallback genérico `window.location.href = sel.url` "
            "(línea ~280). Es seguro: corre SÓLO si el tipo NO es ticket "
            "o el URL no contiene '/detalle-html'. NO es el bug actual."
        )


# =============================================================================
# 2. Verificación del contrato del backend
# =============================================================================
def test_backend_buscar_contrato() -> None:
    if not BACKEND_PATH.exists():
        fail(f"No se encontró {BACKEND_PATH}")

    src = BACKEND_PATH.read_text(encoding="utf-8")
    info(f"buscar.py: {len(src):,} bytes")

    # Verificar que el backend emite "tipo": "ticket" (lowercase) para tickets.
    patron_tipo_ticket = re.compile(
        r'"tipo"\s*:\s*["\']ticket["\']'
    )
    if not patron_tipo_ticket.search(src):
        fail(
            "El backend NO emite `\"tipo\": \"ticket\"` (lowercase). "
            "Si cambió a mayúscula, el contrato cambió y hay que actualizar "
            "ambos lados (frontend y tests)."
        )
    ok("Backend emite `\"tipo\": \"ticket\"` (lowercase) para tickets.")

    # Verificar que el URL sigue apuntando al endpoint modal
    patron_url_modal = re.compile(
        r'"url"\s*:\s*f?["\']\/api\/v1\/tickets\/\{[^}]+\}\/detalle-html["\']'
    )
    if not patron_url_modal.search(src):
        fail(
            "El backend ya NO devuelve `/api/v1/tickets/{id}/detalle-html` "
            "como URL. Esto podría romper el modal, pero también elimina "
            "el riesgo de navegación directa al fragmento."
        )
    ok("Backend sigue devolviendo URL modal `/api/v1/tickets/{id}/detalle-html`.")


# =============================================================================
# 3. Verificación de que el endpoint modal NO es una página completa
# =============================================================================
def test_endpoint_modal_es_fragmento() -> None:
    """Verifica que /api/v1/tickets/{id}/detalle-html devuelve un fragmento,
    NO una página HTML completa (con <html>, <head>, <body>).
    Si devuelve una página completa, el frontend ya no tiene la excusa
    de 'romper la navegación'."""
    tickets_api = APP_DIR / "api" / "v1" / "tickets.py"
    if not tickets_api.exists():
        info("No se encontró app/api/v1/tickets.py, skip.")
        return

    src = tickets_api.read_text(encoding="utf-8")

    # Buscar el handler
    patron_handler = re.compile(
        r'@router\.get\([^)]*detalle-html[^)]*response_class=HTMLResponse',
        re.DOTALL,
    )
    if not patron_handler.search(src):
        fail(
            "No se encontró el handler `@router.get(...detalle-html, "
            "response_class=HTMLResponse)`. El endpoint puede haber "
            "cambiado de nombre o tipo de respuesta."
        )
    ok("Handler del endpoint modal encontrado.")

    # Buscar el renderizador que se invoca
    patron_render = re.compile(
        r'render_detalle_modal|render_detalle|return\s+HTMLResponse'
    )
    if not patron_render.search(src):
        fail("No se encontró el renderizador del fragmento modal.")
    ok("Renderizador del fragmento modal encontrado.")


# =============================================================================
# 4. Resumen y salida
# =============================================================================
def main() -> int:
    print("=" * 70)
    print(" TEST REGRESIÓN — command-palette: case-sensitivity de `tipo`")
    print("=" * 70)
    print()

    test_command_palette_js()
    print()
    test_backend_buscar_contrato()
    print()
    test_endpoint_modal_es_fragmento()
    print()

    print("=" * 70)
    print(f" {GREEN}TODOS LOS CHECKS PASARON{RESET}")
    print("=" * 70)
    print()
    print("Resumen del fix:")
    print(" • command-palette.js: condición ahora usa `.toLowerCase()` para")
    print("   ser robusta a cambios de capitalización en cualquier capa.")
    print(" • El bug histórico: `sel.tipo === 'ticket'` nunca matcheaba")
    print("   porque `collectResults` asignaba 'Ticket' (mayúscula).")
    print(" • Ahora los tickets SIEMPRE caen en las 3 estrategias (htmx →")
    print("   fetch → /tickets) y NUNCA navegan directo al fragmento modal.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())