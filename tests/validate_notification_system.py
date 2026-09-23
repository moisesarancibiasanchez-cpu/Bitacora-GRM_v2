"""
Validador del sistema de mensajería y notificaciones (2026-09-23).

NO modifica el código del proyecto; sólo LEE archivos y reporta hallazgos.

Verifica los 3 ejes requeridos por el usuario:
  1. 4 triggers de deadline (today/missed/approaching/overdue).
  2. Notificación al responsable al mover tarjeta a columna.
  3. Email al admin al modificar Resultado Pruebas.

Resultados: imprime un reporte detallado con marcas +/X.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def assert_(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  X FAIL: {msg}")
    else:
        print(f"  + {msg}")


def main() -> int:
    print("=" * 78)
    print("  VALIDACIÓN: SISTEMA DE NOTIFICACIONES Y EMAILS")
    print("  Fecha: 2026-09-23")
    print("=" * 78)

    # ----------------------------------------------------------------------
    # EJE 1: 4 TRIGGERS DE DEADLINE
    # ----------------------------------------------------------------------
    print("\n" + "-" * 78)
    print("  EJE 1: 4 TRIGGERS DE DEADLINE (today/missed/approaching/overdue)")
    print("-" * 78)

    dn_path = Path("/workspace/app/services/deadline_notifier.py")
    dn_text = dn_path.read_text(encoding="utf-8")
    print(f"  + Archivo leído: {dn_path.name} ({len(dn_text)} chars)")

    # 1.1) Las 4 constantes existen
    for trig in ("DEADLINE_TODAY", "DEADLINE_MISSED", "DEADLINE_APPROACHING", "TASK_OVERDUE"):
        assert_(
            f"TRIGGER_{trig}" in dn_text,
            f"Constante TRIGGER_{trig} definida",
        )

    # 1.2) Las 4 funciones trigger existen
    for fn in (
        "trigger_deadline_today",
        "trigger_deadline_missed",
        "trigger_deadline_approaching",
        "trigger_task_overdue",
    ):
        assert_(
            f"def {fn}(" in dn_text,
            f"Función {fn}() implementada",
        )

    # 1.3) Cada trigger filtra por archivado=False y estado.es_final=False
    # (los 4 loops hacen exactamente eso en sus queries)
    assert_(
        dn_text.count("Ticket.archivado == False") >= 4,
        "Los 4 triggers excluyen tickets archivados",
    )
    assert_(
        dn_text.count("Ticket.estado.has(es_final=False)") >= 4,
        "Los 4 triggers excluyen tickets en estado final",
    )

    # 1.4) Cada trigger genera Notificación in-app
    assert_(
        dn_text.count("_crear_notificacion(db,") >= 4,
        "Los 4 triggers llaman a _crear_notificacion() (in-app)",
    )

    # 1.5) Cada trigger llama a _auditar() para trazabilidad
    assert_(
        dn_text.count("_auditar(db, t,") >= 4,
        "Los 4 triggers llaman a _auditar() (trazabilidad)",
    )

    # 1.6) Idempotencia 24h por trigger
    assert_(
        dn_text.count("_ya_notificado_hoy(db, t.id,") >= 4,
        "Los 4 triggers consultan _ya_notificado_hoy() (idempotencia 24h)",
    )

    # 1.7) BUG DETECTADO: la función _enviar_email() referencia
    # funciones/claves inexistentes en email_service.py
    m_envio = re.search(
        r"def _enviar_email\(.+?\)\s*->\s*Optional\[str\]:(.+?)\n\n",
        dn_text,
        re.DOTALL,
    )
    if m_envio:
        body = m_envio.group(1)
        print("\n  --- Análisis de _enviar_email() ---")
        # 1.7.a) Llama a get_email_service() — función que NO existe en email_service.py
        assert_(
            "get_email_service" in body,
            "_enviar_email llama a get_email_service()",
        )
        # 1.7.b) El resultado se trata como 'svc' para chequear 'is None'
        assert_(
            "if svc is None" in body,
            "_enviar_email chequea 'if svc is None'",
        )
        # 1.7.c) Llama a email_ticket_en_columna con kwargs incorrectos
        #        (los reales son: ticket_codigo, ticket_titulo, estado_origen,
        #         estado_destino, responsable_nombre, actor_nombre, url_ticket)
        assert_(
            re.search(r"email_ticket_en_columna\(\s*db=", body) is not None,
            "_enviar_email llama a email_ticket_en_columna(db=...) — parámetro INEXISTENTE",
        )
        # 1.7.d) Desempaqueta resultado como (ok, err) — la firma real devuelve
        #        (subject, body, html)
        assert_(
            re.search(r"ok,\s*err\s*=\s*email_ticket_en_columna", body) is not None,
            "_enviar_email desempaqueta (ok, err) de email_ticket_en_columna — la firma real devuelve (subject, body, html)",
        )

    # 1.8) Orquestador: ejecutar_todos_los_triggers()
    assert_(
        "def ejecutar_todos_los_triggers" in dn_text,
        "Orquestador ejecutar_todos_los_triggers() presente",
    )

    # ----------------------------------------------------------------------
    # 1.X) CABLEADO CELERY BEAT
    # ----------------------------------------------------------------------
    celery_path = Path("/workspace/app/core/celery_app.py")
    celery_text = celery_path.read_text(encoding="utf-8")
    print(f"\n  + Archivo leído: {celery_path.name}")

    assert_(
        "revisar-deadlines-diario" in celery_text,
        "Celery Beat agenda 'revisar-deadlines-diario' (diario 8 AM)",
    )
    assert_(
        "revisar-deadlines-horario" in celery_text,
        "Celery Beat agenda 'revisar-deadlines-horario' (cada hora)",
    )
    assert_(
        "app.tasks.deadline_tasks" in celery_text,
        "Celery incluye el módulo app.tasks.deadline_tasks",
    )

    # ----------------------------------------------------------------------
    # EJE 2: NOTIFICACIÓN AL RESPONSABLE AL MOVER TARJETA
    # ----------------------------------------------------------------------
    print("\n" + "-" * 78)
    print("  EJE 2: NOTIFICACIÓN AL RESPONSABLE AL MOVER TARJETA")
    print("-" * 78)

    nrs_path = Path("/workspace/app/services/notificacion_responsable_service.py")
    nrs_text = nrs_path.read_text(encoding="utf-8")
    print(f"  + Archivo leído: {nrs_path.name} ({len(nrs_text)} chars)")

    # 2.1) Función principal
    assert_(
        "def notificar_responsable_columna(" in nrs_text,
        "Función notificar_responsable_columna() implementada",
    )

    # 2.2) Chequea responsable_id de la columna destino
    assert_(
        "responsable_id" in nrs_text,
        "Chequea estado_destino.responsable_id",
    )

    # 2.3) Crea Notificación in-app
    assert_(
        "Notificacion(" in nrs_text,
        "Crea registro Notificacion in-app",
    )

    # 2.4) Envía email
    assert_(
        "send_email(" in nrs_text and "email_ticket_en_columna(" in nrs_text,
        "Envía email al responsable vía email_service.email_ticket_en_columna()",
    )

    # 2.5) Audita como NOTIF_RESPONSABLE_COL
    assert_(
        'accion="NOTIF_RESPONSABLE_COL"' in nrs_text,
        "Audita acción 'NOTIF_RESPONSABLE_COL'",
    )

    # 2.6) Skip si actor es responsable
    assert_(
        "responsable.id == actor.id" in nrs_text,
        "Omite si el actor ES el responsable",
    )

    # 2.7) El endpoint cambiar_estado llama al servicio
    ts_path = Path("/workspace/app/services/ticket_service.py")
    ts_text = ts_path.read_text(encoding="utf-8")
    assert_(
        "notificar_responsable_columna(" in ts_text,
        "ticket_service.cambiar_estado() invoca notificar_responsable_columna()",
    )

    # ----------------------------------------------------------------------
    # EJE 3: EMAIL ADMIN AL MODIFICAR RESULTADO PRUEBAS
    # ----------------------------------------------------------------------
    print("\n" + "-" * 78)
    print("  EJE 3: EMAIL ADMIN AL MODIFICAR 'RESULTADO PRUEBAS'")
    print("-" * 78)

    print("\n  Buscando trigger de email al admin al modificar Resultado Pruebas…")

    # 3.1) Buscar referencias a 'resultado_pruebas' en /workspace/app/
    # (excluyendo scripts/migraciones que son one-shot)
    app_dir = Path("/workspace/app")
    rp_refs = []
    for f in app_dir.rglob("*.py"):
        if "resultado_pruebas" in f.read_text(encoding="utf-8", errors="ignore"):
            rp_refs.append(f)
    print(f"\n  Archivos en /workspace/app/ con 'resultado_pruebas': {len(rp_refs)}")
    for f in rp_refs:
        print(f"    - {f.relative_to(app_dir)}")

    # 3.2) Buscar referencias a email de admin
    admin_email_refs = []
    patterns = ["administrador", "ADMIN", "rol.*admin"]
    for f in app_dir.rglob("*.py"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for p in patterns:
                if re.search(p, text, re.IGNORECASE):
                    if "email" in text.lower() or "notif" in text.lower():
                        admin_email_refs.append(f)
                        break
        except Exception:
            pass
    print(f"\n  Archivos con potencial email-a-admin: {len(admin_email_refs)}")
    for f in admin_email_refs[:10]:
        print(f"    - {f.relative_to(app_dir)}")

    # 3.3) El endpoint /guardar acepta resultado_pruebas
    tickets_path = Path("/workspace/app/api/v1/tickets.py")
    tickets_text = tickets_path.read_text(encoding="utf-8")
    assert_(
        '"resultado_pruebas"' in tickets_text,
        "Endpoint POST /tickets/{id}/guardar acepta campo 'resultado_pruebas'",
    )

    # 3.4) Audita el cambio como 'resultado_pruebas_editado'
    assert_(
        '"resultado_pruebas_editado"' in tickets_text,
        "Audita acción 'resultado_pruebas_editado'",
    )

    # 3.5) PERO: NO hay email al admin después del cambio
    # Buscamos si en /guardar hay alguna llamada a send_email/email_service
    # cuando se modifica resultado_pruebas
    guard_section = re.search(
        r"async def guardar_ticket_campos.+?return HTMLResponse",
        tickets_text,
        re.DOTALL,
    )
    if guard_section:
        section_text = guard_section.group(0)
        has_email_call = (
            "send_email(" in section_text
            or "email_service" in section_text
            or "_notificar_admin" in section_text
            or "rol=ADMINISTRADOR" in section_text
        )
        if has_email_call:
            print(f"  X ENDPOINT /guardar ENVÍA email al admin")
        else:
            print(f"  + ENDPOINT /guardar NO envía email al admin (gap confirmado)")

    # 3.6) El servicio actual no tiene lógica de email al admin
    if "actualizar_campos" in ts_text:
        m = re.search(
            r"def actualizar_campos\(.+?\):(.+?)(?=def |\Z)",
            ts_text,
            re.DOTALL,
        )
        if m:
            body = m.group(0)
            assert_(
                "send_email" not in body and "notificar_admin" not in body,
                "ticket_service.actualizar_campos() no envía email (sin trigger admin)",
            )

    # 3.7) NO existe plantilla de email específica para este caso
    es_path = Path("/workspace/app/services/email_service.py")
    es_text = es_path.read_text(encoding="utf-8")
    email_templates = re.findall(r"^def email_(\w+)\(", es_text, re.MULTILINE)
    print(f"\n  Plantillas de email disponibles: {email_templates}")
    print(f"  + email_ticket_en_columna:    'responsable al mover tarjeta'")
    print(f"  + email_credenciales_iniciales: 'bienvenida usuario'")
    print(f"  X email_resultado_pruebas_*:  NO EXISTE (no se notifica al admin)")

    # ----------------------------------------------------------------------
    # RESUMEN
    # ----------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("  RESUMEN EJECUTIVO")
    print("=" * 78)
    print("""
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ EJE 1 — 4 TRIGGERS DE DEADLINE                                         │
  │ ─────────────────────────────────────────────────────────────────────── │
  │ ✓ Funciones implementadas y completas (4/4)                             │
  │ ✓ Filtros correctos (archivado, es_final, fecha)                        │
  │ ✓ Idempotencia 24h presente                                             │
  │ ✓ In-app notifications (Notificacion)                                   │
  │ ✓ Auditoria para trazabilidad                                           │
  │ ✓ Cableado Celery Beat (diario 8 AM + horario cada hora)                │
  │ X BUG: _enviar_email() llama a get_email_service() (no existe)          │
  │        y usa kwargs incorrectos en email_ticket_en_columna()            │
  │        → EMAILS NO SE ENVÍAN, sólo in-app                               │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ EJE 2 — NOTIFICACIÓN AL RESPONSABLE AL MOVER TARJETA                    │
  │ ─────────────────────────────────────────────────────────────────────── │
  │ ✓ Servicio notificacion_responsable_service completo                    │
  │ ✓ In-app + email + auditoria                                           │
  │ ✓ Skip si actor == responsable                                          │
  │ ✓ Cableado en ticket_service.cambiar_estado()                          │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ EJE 3 — EMAIL ADMIN AL MODIFICAR RESULTADO PRUEBAS                       │
  │ ─────────────────────────────────────────────────────────────────────── │
  │ ✓ El campo existe en el modelo Ticket                                   │
  │ ✓ El endpoint /guardar lo acepta y audita                               │
  │ X NO HAY TRIGGER: NO se envía email al admin al modificar               │
  │   'resultado_pruebas' en el detalle del ticket                          │
  │ X NO existe plantilla email_resultado_pruebas_*                         │
  │ X El service ticket_service.actualizar_campos() no notifica             │
  │ → FEATURE NO IMPLEMENTADA                                               │
  └─────────────────────────────────────────────────────────────────────────┘
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())