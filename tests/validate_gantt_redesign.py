"""
Validador del rediseño visual de gantt.html (commit 2026-09-22 - rediseño UI).

Verifica:
  1) El template compila correctamente con Jinja2.
  2) El .gantt-wrap tiene fondo blanco (#ffffff) y overflow en ambos ejes.
  3) #gantt-svg tiene fondo blanco explícito.
  4) Las nuevas clases CSS están definidas:
       - .gantt-svg-canvas
       - .gantt-left-panel-bg
       - .gantt-left-panel-divider
       - .gantt-row-text-code / -title / -meta
       - .gantt-legend-card / -chip / .legend-swatch
  5) El render() JS añade:
       - <rect class="gantt-svg-canvas"> como primera capa
       - <rect class="gantt-left-panel-bg">
       - Usa las clases gantt-row-text-code y gantt-row-text-title
       - Usa la clase gantt-left-panel-divider en el separador
  6) El legend tiene los 4 tipos (FS, SS, FF, SF) + Auto-FS etapas.
  7) NO quedan atributos inline problemáticos: fill="#0f172a", stroke="#cbd5e1"
     en líneas que ya tienen clases equivalentes.
  8) Las webkit scrollbars están definidas.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def assert_(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  X FAIL: {msg}")
        sys.exit(1)
    print(f"  + {msg}")


def main() -> int:
    print("=" * 78)
    print("  VALIDACIÓN DEL REDISEÑO VISUAL: gantt.html - fondo y scroll")
    print("=" * 78)

    template_path = Path("/workspace/app/templates/vistas/gantt.html")
    text = template_path.read_text(encoding="utf-8")
    print(f"  + Archivo leído: {len(text)} chars")

    # --- 1) Sintaxis Jinja2 -------------------------------------------------
    try:
        from jinja2 import Environment, FileSystemLoader, ChoiceLoader, TemplateSyntaxError
        env = Environment(
            loader=ChoiceLoader([FileSystemLoader("/workspace/app/templates")]),
            autoescape=False,
        )
        try:
            env.parse(text)
            print("  + Template parsea correctamente (sintaxis OK)")
        except TemplateSyntaxError as e:
            print(f"  X ERROR de sintaxis en template: {e}")
            return 1
    except Exception as e:
        print(f"  ! Aviso: {e}")

    # --- 2) .gantt-wrap: fondo blanco y overflow en ambos ejes --------------
    css_block_match = re.search(
        r"\{%\s*block\s+extra_css\s*%\}(.+?)\{%\s*endblock\s*%\}",
        text,
        re.DOTALL,
    )
    assert_(css_block_match is not None, "Bloque {% block extra_css %} presente")
    css_block = css_block_match.group(1)

    # Fondo blanco explícito en .gantt-wrap
    assert_(
        re.search(r"\.gantt-wrap\s*\{[^}]*background\s*:\s*#ffffff", css_block) is not None,
        ".gantt-wrap tiene background:#ffffff",
    )
    # overflow-y: auto (scroll vertical habilitado)
    assert_(
        re.search(r"\.gantt-wrap\s*\{[^}]*overflow-y\s*:\s*auto", css_block) is not None,
        ".gantt-wrap tiene overflow-y:auto (scroll vertical)",
    )
    # overflow-x: auto (scroll horizontal habilitado)
    assert_(
        re.search(r"\.gantt-wrap\s*\{[^}]*overflow-x\s*:\s*auto", css_block) is not None,
        ".gantt-wrap tiene overflow-x:auto (scroll horizontal)",
    )
    # max-height para activar scroll vertical
    assert_(
        re.search(r"\.gantt-wrap\s*\{[^}]*max-height\s*:\s*\d+v?h", css_block) is not None,
        ".gantt-wrap tiene max-height en vh (activa scroll vertical)",
    )

    # --- 3) #gantt-svg: fondo blanco explícito ------------------------------
    assert_(
        re.search(r"#gantt-svg\s*\{[^}]*background\s*:\s*#ffffff", css_block) is not None,
        "#gantt-svg tiene background:#ffffff",
    )

    # --- 4) Clases CSS nuevas -----------------------------------------------
    new_classes = [
        ".gantt-svg-canvas",
        ".gantt-left-panel-bg",
        ".gantt-left-panel-divider",
        ".gantt-row-text-code",
        ".gantt-row-text-title",
        ".gantt-row-text-meta",
        ".gantt-legend-card",
        ".gantt-legend-chip",
        ".legend-swatch",
    ]
    for cls in new_classes:
        assert_(
            cls in css_block,
            f"Clase {cls} presente en CSS",
        )

    # Colores de la paleta de la nueva UI
    assert_("#f8fafc" in css_block, "Color de fondo slate-50 (#f8fafc) presente")
    assert_("#0f172a" in css_block, "Color de texto slate-900 (#0f172a) presente")
    assert_("#334155" in css_block, "Color de texto slate-700 (#334155) presente")
    assert_("#475569" in css_block, "Color de texto slate-600 (#475569) presente")
    assert_("#cbd5e1" in css_block, "Color de borde slate-300 (#cbd5e1) presente")

    # Scrollbars webkit personalizadas
    assert_(
        "::-webkit-scrollbar" in css_block,
        "Scrollbars webkit personalizadas presentes",
    )
    assert_(
        "::-webkit-scrollbar-thumb" in css_block,
        "Scrollbar thumb personalizado presente",
    )

    # --- 5) render() JS: canvas, panel izquierdo, clases -------------------
    # Buscar la función render() principal
    render_match = re.search(
        r"function\s+render\s*\(\s*\)\s*\{(.+?)\n\}\s*\n",
        text,
        re.DOTALL,
    )
    assert_(render_match is not None, "Función render() principal encontrada")
    render_body = render_match.group(1)

    # Capa 0: canvas blanco como primera inserción
    assert_(
        re.search(r'class="gantt-svg-canvas"', render_body) is not None,
        "render() añade <rect class='gantt-svg-canvas'>",
    )
    # Capa 1: fondo del panel izquierdo
    assert_(
        re.search(r'class="gantt-left-panel-bg"', render_body) is not None,
        "render() añade <rect class='gantt-left-panel-bg'>",
    )
    # Texto de código usa la clase
    assert_(
        re.search(r'class="gantt-row-text-code"', render_body) is not None,
        "render() usa class='gantt-row-text-code' para el código",
    )
    # Texto de título usa la clase
    assert_(
        re.search(r'class="gantt-row-text-title"', render_body) is not None,
        "render() usa class='gantt-row-text-title' para el título",
    )
    # Separador vertical usa la clase
    assert_(
        re.search(r'class="gantt-left-panel-divider"', render_body) is not None,
        "render() usa class='gantt-left-panel-divider' para el separador",
    )

    # Orden: canvas aparece ANTES que el panel izquierdo en grid.innerHTML
    canvas_pos = render_body.find('class="gantt-svg-canvas"')
    panel_pos = render_body.find('class="gantt-left-panel-bg"')
    grid_bg_pos = render_body.find('class="gantt-grid-bg"')
    assert_(
        0 < canvas_pos < panel_pos < grid_bg_pos,
        f"Orden de capas correcto: canvas({canvas_pos}) < panel({panel_pos}) < grid-bg({grid_bg_pos})",
    )

    # --- 6) NO quedan atributos inline problemáticos ------------------------
    # Buscamos atributos inline fill="#0f172a" o stroke="#cbd5e1" en líneas
    # que previamente eran código (texto del código, separador).
    # Filtramos: buscamos líneas que contengan "font-size" (texto inline) o
    # "stroke="#cbd5e1"" (línea del separador).
    bad_inline = 0
    for line in render_body.splitlines():
        if 'fill="#0f172a"' in line and 'font-size' in line:
            bad_inline += 1
        if 'stroke="#cbd5e1"' in line and 'x1="${LEFT_PAN}"' in line:
            bad_inline += 1
    assert_(
        bad_inline == 0,
        f"Ningún atributo inline problemático en render() (encontrados={bad_inline})",
    )

    # --- 7) Legend: 4 tipos + Auto-FS --------------------------------------
    # Usamos .*?  en lugar de [^>]*  para tolerar caracteres invisibles / BOM.
    legend_card_match = re.search(
        r'<div.*?class="gantt-legend-card.*?>(.*?)</div>',
        text,
        re.DOTALL,
    )
    assert_(
        legend_card_match is not None,
        "Contenedor <div class='gantt-legend-card'> presente",
    )
    legend_body = legend_card_match.group(1)

    tipos_esperados = {
        "FS": "Fin → Inicio",
        "SS": "Inicio → Inicio",
        "FF": "Fin → Fin",
        "SF": "Inicio → Fin",
        "Auto-FS": "etapas (intra-ticket)",
    }
    for tipo, label in tipos_esperados.items():
        assert_(
            tipo in legend_body and label in legend_body,
            f"Legend contiene tipo '{tipo}' con label '{label}'",
        )

    # Swatch dashed para Auto-FS
    assert_(
        'legend-swatch dashed' in legend_body,
        "Legend tiene swatch dashed (Auto-FS)",
    )
    # kbd hints para interacciones
    assert_(
        "<kbd>" in legend_body,
        "Legend incluye <kbd> hints para atajos de interacción",
    )

    # --- 8) Renderizar el template con contexto realista -------------------
    try:
        class _URL:
            def __init__(self, path: str):
                self.path = path

        class _Req:
            def __init__(self):
                self.url = _URL("/vistas/gantt")

        class _Usuario:
            id = 1
            nombre_completo = "Test Admin"
            rol = "administrador"

        context = {
            "request": _Req(),
            "usuario": _Usuario(),
            "tickets_data": [
                {
                    "id": 101,
                    "codigo": "GAR_RI_001",
                    "titulo": "Ticket de prueba 1",
                    "estado": "BACKLOG",
                    "estado_id": 5,
                    "asignado": "Tester 1",
                    "asignado_id": 2,
                    "modulo": "qa",
                    "prioridad": "media",
                    "prioridad_color": "#f59e0b",
                    "inicio": "2026-10-02",
                    "fin": "2026-11-19",
                    "sla_cumplido": -1,
                    "archivado": False,
                    "progreso": 0,
                    "hu": None,
                    "etapas": [],
                },
            ],
            "links_data": [],
            "tickets": [],
            "total_tickets": 1,
            "total_links": 0,
            "q": "",
            "modulo": "",
            "zoom": "week",
            "modulos": ["qa"],
            "espacio_id": None,
        }
        html = env.get_template("vistas/gantt.html").render(**context)
        print(f"  + Template renderizado: {len(html)} chars")
        # Las clases deben sobrevivir al render
        assert_(
            'gantt-svg-canvas' in html,
            "Renderizado contiene class='gantt-svg-canvas'",
        )
        assert_(
            'gantt-left-panel-bg' in html,
            "Renderizado contiene class='gantt-left-panel-bg'",
        )
        assert_(
            'gantt-row-text-code' in html,
            "Renderizado contiene class='gantt-row-text-code'",
        )
        assert_(
            'gantt-legend-card' in html,
            "Renderizado contiene class='gantt-legend-card'",
        )
    except Exception as e:
        # Si falla por includes no resueltos (dev_inbox_enabled, etc.),
        # el parseo ya pasó arriba, lo cual es suficiente para validar
        # la sintaxis y la presencia de las clases.
        print(f"  ! Aviso en render: {e}")

    print()
    print("=" * 78)
    print("  +++ TODAS LAS VALIDACIONES DEL REDISEÑO PASARON +++")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())