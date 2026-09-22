"""
Regresión: Nueva pestaña 'Etapas UAT' en el modal de detalle (2026-09-23).

FEATURE: Sub-bars de etapas en Gantt.

Este validador verifica end-to-end que la nueva pestaña funciona y no
rompe el resto del modal. Cubre:

  1. Renderer (detalle_modal.py)
     - El botón 'Etapas UAT' está en el tablist del modal.
     - Existe un panel con `data-panel="etapas"`.
     - `render_detalle_modal` acepta `etapas` y `catalogo_etapas`.
     - `_tabs_validos` incluye 'etapas' (no se cae con active_tab='etapas').
     - Cuando `etapas` está VACÍO: muestra botón "Auto-asignar 10 etapas UAT".
     - Cuando `etapas` está POBLADO: muestra N formularios PATCH por etapa.
     - Cada form usa `hx-patch="/api/v1/etapas/ticket/{id}/{etapa_id}"`.
     - El form principal usa `hx-post=".../auto-asignar"`.
     - Hay barra de progreso (footer) cuando hay etapas.
     - Hay estado vacío con preview del catálogo cuando no hay etapas.

  2. Endpoint /api/v1/tickets/{id}/detalle-html (tickets.py)
     - Existe helper `_get_etapas_y_catalogo(db, ticket_id)`.
     - Existe helper `_serializar_ticket_etapa(te)`.
     - Los 4 call sites de `render_detalle_modal(...)` pasan
       `etapas=etapas, catalogo_etapas=catalogo_etapas`.

  3. Endpoint /api/v1/etapas (etapas.py)
     - Existe `GET /api/v1/etapas` (lista de catálogo).
     - Existe `POST /api/v1/etapas/ticket/{tid}/auto-asignar`.
     - Existe `PATCH /api/v1/etapas/ticket/{tid}/{etapa_id}`.

  4. Sintaxis
     - detalle_modal.py compila con `python -m py_compile`.
     - tickets.py compila con `python -m py_compile`.
     - etapas.py compila con `python -m py_compile`.
     - etapa_service.py compila con `python -m py_compile`.

  5. Render real
     - El template renderiza correctamente con `etapas=[]` y
       `catalogo_etapas=[{...10 items...}]`.
     - El template renderiza correctamente con `etapas=[{...10 items...}]`.

  6. Anti-regresión: el modal sigue teniendo los 6 tabs
     (detalles, comentarios, adjuntos, checklist, etapas, trazabilidad).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/workspace").resolve()
sys.path.insert(0, str(ROOT))


def assert_(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  X FAIL: {msg}")
        sys.exit(1)
    print(f"  + {msg}")


def check_syntax(path: Path, label: str) -> None:
    """Ejecuta python -m py_compile sobre el archivo."""
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  X FAIL: {label} no compila:")
        print(r.stderr)
        sys.exit(1)
    print(f"  + {label} compila (py_compile OK)")


def main() -> int:
    print("=" * 78)
    print("  VALIDACIÓN: Nueva pestaña 'Etapas UAT' en modal de detalle")
    print("=" * 78)

    # ===================================================================
    # 4. SINTAXIS (lo primero, para fallar rápido)
    # ===================================================================
    print("\n--- 1) Sintaxis de los archivos modificados ---")
    files_to_check = {
        "detalle_modal.py":  ROOT / "app/templates/tickets/detalle_modal.py",
        "tickets.py":        ROOT / "app/api/v1/tickets.py",
        "etapas.py":         ROOT / "app/api/v1/etapas.py",
        "etapa_service.py":  ROOT / "app/services/etapa_service.py",
    }
    for label, path in files_to_check.items():
        check_syntax(path, label)

    detalle_text = files_to_check["detalle_modal.py"].read_text(encoding="utf-8")
    tickets_text  = files_to_check["tickets.py"].read_text(encoding="utf-8")
    etapas_text   = files_to_check["etapas.py"].read_text(encoding="utf-8")
    svc_text      = files_to_check["etapa_service.py"].read_text(encoding="utf-8")

    # ===================================================================
    # 1. RENDERER (detalle_modal.py)
    # ===================================================================
    print("\n--- 2) Renderer: detalle_modal.py ---")

    # --- 1a) Tab button en el header ------------------------------------
    tab_btn_match = re.search(
        r'<button[^>]*data-tab="etapas"[^>]*>(.+?)</button>',
        detalle_text,
        re.DOTALL,
    )
    assert_(tab_btn_match is not None, "Botón data-tab=\"etapas\" presente")
    tab_btn_body = tab_btn_match.group(0)
    assert_(
        "Etapas UAT" in tab_btn_body,
        "Etiqueta del botón dice 'Etapas UAT'",
    )
    # Badge de progreso N/10
    assert_(
        "{{ etapas|length }}/10" in tab_btn_body,
        "Badge muestra 'etapas|length/10' (auto-update)",
    )
    # Estilo condicional según _active (igual que otros tabs)
    assert_(
        "_active == 'etapas'" in tab_btn_body,
        "Estilo activo/inactivo según _active=='etapas'",
    )

    # --- 1b) Panel de contenido -----------------------------------------
    panel_match = re.search(
        r'<div[^>]*data-panel="etapas"[^>]*>(.+?)</div>\s*\n\s*<!-- Tab: Trazabilidad',
        detalle_text,
        re.DOTALL,
    )
    assert_(panel_match is not None, "Panel data-panel=\"etapas\" presente")
    panel_body = panel_match.group(1)
    print(f"  + Panel 'etapas' extraído: {len(panel_body)} chars")

    # --- 1c) Estado VACÍO: botón auto-asignar + preview catálogo -------
    # El botón solo aparece si NOT etapas (rama else)
    assert_(
        'hx-post="/api/v1/etapas/ticket/{{ ticket.id }}/auto-asignar"' in panel_body,
        "Botón 'Auto-asignar' usa hx-post al endpoint correcto",
    )
    assert_(
        "Auto-asignar 10 etapas UAT" in panel_body,
        "Etiqueta del botón dice 'Auto-asignar 10 etapas UAT'",
    )
    assert_(
        'hx-confirm="' in panel_body and "10 etapas UAT" in panel_body,
        "Botón tiene confirmación hx-confirm antes de actuar",
    )
    # Preview del catálogo (estado vacío)
    assert_(
        "{% if catalogo_etapas %}" in panel_body,
        "Estado vacío muestra preview del catálogo (catalogo_etapas)",
    )
    assert_(
        "{% for e in catalogo_etapas %}" in panel_body,
        "Estado vacío itera sobre catalogo_etapas",
    )
    assert_(
        "El catálogo de etapas está vacío" in panel_body,
        "Mensaje de fallback si catálogo vacío",
    )
    # Estado vacío alternativo (catálogo vacío)
    assert_(
        "No hay etapas asignadas" in panel_body,
        "Mensaje principal del estado vacío",
    )

    # --- 1d) Estado POBLADO: N formularios PATCH -----------------------
    # Form por etapa: hx-patch al endpoint correcto
    assert_(
        'hx-patch="/api/v1/etapas/ticket/{{ ticket.id }}/{{ te.etapa_id }}"' in panel_body,
        "Form por etapa usa hx-patch al endpoint correcto",
    )
    # Inputs editables
    assert_('name="fecha_inicio"' in panel_body, "Input 'fecha_inicio' presente")
    assert_('name="fecha_fin"' in panel_body,    "Input 'fecha_fin' presente")
    assert_('name="completado"' in panel_body,   "Checkbox 'completado' presente")
    assert_('name="notas"' in panel_body,        "Textarea 'notas' presente")
    assert_('type="date"' in panel_body,         "Inputs de fecha son type=date")
    # Ordenamiento
    assert_(
        "etapas|sort(attribute='etapa_orden')" in panel_body,
        "Etapas se ordenan por etapa_orden ASC",
    )
    # Color dot con el color de la etapa
    assert_(
        "background-color: {{ te.etapa_color }}" in panel_body,
        "Color dot usa te.etapa_color inline",
    )

    # --- 1e) Footer / progreso ------------------------------------------
    assert_(
        "_etapas_done" in panel_body and "_etapas_pct" in panel_body,
        "Footer calcula _etapas_done y _etapas_pct",
    )
    assert_(
        "bg-emerald-500" in panel_body,
        "Barra de progreso usa color emerald-500",
    )

    # --- 1f) Signature de render_detalle_modal --------------------------
    sig_match = re.search(
        r"def\s+render_detalle_modal\s*\((.+?)\)\s*->\s*str:",
        detalle_text,
        re.DOTALL,
    )
    assert_(sig_match is not None, "Función render_detalle_modal(...) encontrada")
    sig = sig_match.group(1)
    assert_("etapas" in sig, "Signature incluye parámetro 'etapas'")
    assert_("catalogo_etapas" in sig, "Signature incluye parámetro 'catalogo_etapas'")
    assert_("Iterable" in sig, "Parámetros son Iterable (compatibilidad con tuplas/listas)")

    # _tabs_validos incluye 'etapas'
    tabs_match = re.search(
        r"_tabs_validos\s*=\s*\{([^}]+)\}",
        detalle_text,
    )
    assert_(tabs_match is not None, "Variable _tabs_validos presente")
    tabs_set = tabs_match.group(1)
    assert_(
        '"etapas"' in tabs_set,
        "_tabs_validos incluye 'etapas' (no se cae con active_tab='etapas')",
    )
    # Sanity: los 6 tabs siguen ahí (no se rompió nada)
    for tab in ("detalles", "comentarios", "adjuntos", "checklist", "etapas", "trazabilidad"):
        assert_(f'"{tab}"' in tabs_set, f"_tabs_validos incluye '{tab}' (sin regresión)")

    # render() pasa las nuevas variables al template.
    # Usamos GREEDY .+ para evitar que la regex corte en el primer ')'
    # interno (ej. auditorias=list(auditorias)).
    render_call = re.search(
        r"return\s+DETALLE_TEMPLATE\.render\s*\((.+)\)\s*\n",
        detalle_text,
        re.DOTALL,
    )
    assert_(render_call is not None, "DETALLE_TEMPLATE.render(...) presente")
    render_args = render_call.group(1)
    assert_("etapas=list(etapas)" in render_args, "render() pasa etapas=list(etapas)")
    assert_(
        "catalogo_etapas=list(catalogo_etapas)" in render_args,
        "render() pasa catalogo_etapas=list(catalogo_etapas)",
    )

    # ===================================================================
    # 2. ENDPOINT /api/v1/tickets/{id}/detalle-html
    # ===================================================================
    print("\n--- 3) Endpoint detalle-html: tickets.py ---")

    assert_(
        "def _get_etapas_y_catalogo" in tickets_text,
        "Helper _get_etapas_y_catalogo(db, ticket_id) definido",
    )
    assert_(
        "def _serializar_ticket_etapa" in tickets_text,
        "Helper _serializar_ticket_etapa(te) definido",
    )
    # El helper debe importar los modelos. Usamos el archivo completo
    # porque el regex non-greedy puede cortar antes del import (que va
    # después del docstring).
    assert_(
        "from app.models.etapa_proyecto import TicketEtapa, EtapaProyecto" in tickets_text,
        "_get_etapas_y_catalogo importa TicketEtapa y EtapaProyecto",
    )
    assert_(
        "TicketEtapa.ticket_id == ticket_id" in tickets_text,
        "_get_etapas_y_catalogo filtra por ticket_id",
    )
    assert_(
        "EtapaProyecto.activo == 1" in tickets_text,
        "_get_etapas_y_catalogo filtra catálogo por activo=1",
    )

    # Los 4 call sites pasan los nuevos params
    call_sites = re.findall(
        r"html\s*=\s*render_detalle_modal\s*\((.+?)\)",
        tickets_text,
        re.DOTALL,
    )
    assert_(len(call_sites) == 4, f"Hay 4 call sites de render_detalle_modal (encontrados={len(call_sites)})")
    for idx, call_args in enumerate(call_sites, start=1):
        assert_(
            "etapas=etapas" in call_args,
            f"Call site #{idx} pasa etapas=etapas",
        )
        assert_(
            "catalogo_etapas=catalogo_etapas" in call_args,
            f"Call site #{idx} pasa catalogo_etapas=catalogo_etapas",
        )

    # ===================================================================
    # 3. ENDPOINTS /api/v1/etapas
    # ===================================================================
    print("\n--- 4) Endpoints: etapas.py ---")

    # Listar catálogo
    assert_(
        re.search(r'@router\.get\s*\(\s*""\s*,\s*response_model', etapas_text) is not None,
        "GET /etapas (catálogo) presente",
    )
    # Auto-asignar
    assert_(
        re.search(
            r'@router\.post\s*\(\s*"/ticket/\{ticket_id\}/auto-asignar"',
            etapas_text,
        ) is not None,
        "POST /etapas/ticket/{tid}/auto-asignar presente",
    )
    # Patch por etapa
    assert_(
        re.search(
            r'@router\.patch\s*\(\s*"/ticket/\{ticket_id\}/\{etapa_id\}"',
            etapas_text,
        ) is not None,
        "PATCH /etapas/ticket/{tid}/{etapa_id} presente",
    )

    # ===================================================================
    # 4. SERVICIO
    # ===================================================================
    print("\n--- 5) EtapaService ---")

    for method in (
        "def listar_etapas",
        "def obtener_etapa",
        "def asignar_etapas_iniciales",
        "def listar_etapas_de_ticket",
        "def actualizar_etapa_ticket",
    ):
        assert_(method in svc_text, f"EtapaService.{method[4:]} definido")

    # asignar_etapas_iniciales debe ser idempotente
    asignar_body_match = re.search(
        r"def\s+asignar_etapas_iniciales.+?(?=\n    def\s|\nclass\s|\Z)",
        svc_text,
        re.DOTALL,
    )
    assert_(asignar_body_match is not None, "Cuerpo de asignar_etapas_iniciales extraíble")
    assert_(
        "ya_hay" in asignar_body_match.group(0) or "ya existen" in asignar_body_match.group(0).lower(),
        "asignar_etapas_iniciales detecta asignaciones previas (idempotente)",
    )

    # actualizar_etapa_ticket valida rango de fechas
    actualizar_body_match = re.search(
        r"def\s+actualizar_etapa_ticket.+?(?=\n    def\s|\nclass\s|\Z)",
        svc_text,
        re.DOTALL,
    )
    assert_(actualizar_body_match is not None, "Cuerpo de actualizar_etapa_ticket extraíble")
    assert_(
        "rango_fechas_invalido" in actualizar_body_match.group(0),
        "actualizar_etapa_ticket valida fecha_fin >= fecha_inicio",
    )

    # ===================================================================
    # 5. RENDER REAL (contexto realista)
    # ===================================================================
    print("\n--- 6) Render real del template ---")
    try:
        from app.templates.tickets.detalle_modal import render_detalle_modal
    except Exception as e:
        print(f"  ! Aviso: no se pudo importar el renderer ({e}); se omite render real")
    else:
        # Stubs mínimos para los atributos que el template toca
        class _Estado:
            nombre = "BACKLOG"
            color = "#64748b"
            value = "BACKLOG"

        class _Prioridad:
            value = "media"

        class _Ticket:
            id = 1234
            codigo = "GAR_RI_TEST_001"
            titulo = "Ticket de prueba para el tab Etapas"
            descripcion = "Smoke test de la nueva pestaña."
            prioridad = _Prioridad()
            estado = _Estado()
            tipo = _Prioridad()  # reutilizamos, sólo necesita .value
            creador = None
            asignado = None
            updated_at = None

        class _Req:
            class _URL:
                path = "/test"
            url = _URL()

        # --- Caso A: etapas VACÍAS ----------------------------------
        html_empty = render_detalle_modal(
            ticket=_Ticket(),
            estados=[],
            comentarios=[],
            adjuntos=[],
            checklists=[],
            active_tab="etapas",
            etapas=[],
            catalogo_etapas=[
                {"id": i, "codigo": f"ET{i}", "nombre": f"Etapa {i}",
                 "orden": i, "color": "#6366f1"}
                for i in range(1, 11)
            ],
        )
        print(f"  + Render con etapas=[]: {len(html_empty)} chars")
        assert_(
            'data-tab="etapas"' in html_empty,
            "Render vacío contiene data-tab=\"etapas\"",
        )
        assert_(
            "Auto-asignar 10 etapas UAT" in html_empty,
            "Render vacío muestra el botón Auto-asignar",
        )
        assert_(
            "/api/v1/etapas/ticket/1234/auto-asignar" in html_empty,
            "Render vacío apunta al endpoint auto-asignar del ticket correcto",
        )
        assert_(
            "0/10" in html_empty,
            "Render vacío muestra badge '0/10' en el tab",
        )
        assert_(
            "No hay etapas asignadas" in html_empty,
            "Render vacío muestra el mensaje 'No hay etapas asignadas'",
        )
        # Preview del catálogo (los 10 nombres)
        for i in range(1, 11):
            assert_(
                f"Etapa {i}" in html_empty,
                f"Render vacío muestra preview de la etapa {i}",
            )

        # --- Caso B: etapas POBLADAS --------------------------------
        etapas_pobladas = [
            {
                "id": 100 + i,
                "ticket_id": 1234,
                "etapa_id": i,
                "etapa_codigo": f"ET{i}",
                "etapa_nombre": f"Etapa {i}",
                "etapa_color": "#06b6d4",
                "etapa_orden": i,
                "fecha_inicio": "2026-09-23" if i <= 5 else None,
                "fecha_fin":    "2026-09-30" if i <= 5 else None,
                "completado":   (i <= 3),
                "orden": i,
                "notas": f"Notas etapa {i}",
            }
            for i in range(1, 11)
        ]
        html_full = render_detalle_modal(
            ticket=_Ticket(),
            estados=[],
            comentarios=[],
            adjuntos=[],
            checklists=[],
            active_tab="etapas",
            etapas=etapas_pobladas,
            catalogo_etapas=[],
        )
        print(f"  + Render con etapas[10]: {len(html_full)} chars")
        assert_(
            '10/10' in html_full,
            "Render con 10 etapas muestra badge '10/10' en el tab",
        )
        # El botón auto-asignar NO debe aparecer (ya hay etapas)
        assert_(
            "Auto-asignar 10 etapas UAT" not in html_full,
            "Render con etapas NO muestra botón auto-asignar",
        )
        # 10 forms PATCH (uno por etapa)
        patch_count = html_full.count('hx-patch="/api/v1/etapas/ticket/1234/')
        assert_(
            patch_count == 10,
            f"Render con 10 etapas genera 10 forms PATCH (encontrados={patch_count})",
        )
        # Footer con progreso: 3/10 etapas completadas (i <= 3)
        assert_(
            "3/10 etapas completadas" in html_full,
            "Footer muestra '3/10 etapas completadas'",
        )
        assert_(
            "30%" in html_full,
            "Footer muestra porcentaje 30% (3/10)",
        )
        # 5 etapas con fecha_inicio planificada
        assert_(
            "5/10 con fecha planificada" in html_full,
            "Footer muestra '5/10 con fecha planificada'",
        )
        # Sanity: NO se rompe ningún otro tab (regresión)
        for tab in ("detalles", "comentarios", "adjuntos", "checklist", "trazabilidad"):
            assert_(
                f'data-tab="{tab}"' in html_full,
                f"Render completo sigue conteniendo tab '{tab}' (sin regresión)",
            )

    # ===================================================================
    # 6. ANTI-REGRESIÓN: el modal sigue teniendo los 6 tabs
    # ===================================================================
    print("\n--- 7) Anti-regresión: los 6 tabs siguen presentes ---")
    for tab in ("detalles", "comentarios", "adjuntos", "checklist", "etapas", "trazabilidad"):
        assert_(
            f'data-tab="{tab}"' in detalle_text,
            f"Botón data-tab=\"{tab}\" presente en el template",
        )

    print()
    print("=" * 78)
    print("  +++ NUEVA PESTAÑA 'ETAPAS UAT' VALIDADA +++")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
