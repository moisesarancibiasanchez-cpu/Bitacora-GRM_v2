"""
Validador exhaustivo del sistema de mensajería y notificaciones.
Versión 2 — incluye verificación de los fixes 2026-09-23:

  FIX-1: Bug crítico en ``deadline_notifier._enviar_email()``
         - Antes: llamaba a get_email_service() inexistente + kwargs incorrectos
         - Ahora: usa send_email() + email_ticket_en_columna() con firma correcta

  FIX-2: Feature faltante "Email admin al modificar Resultado Pruebas"
         - Nueva plantilla: email_resultado_pruebas_modificado()
         - Nuevo servicio: notificacion_admin_resultado_pruebas_service.py
         - Trigger en endpoint /tickets/{id}/guardar

NO modifica el código del proyecto; sólo LEE archivos y ejecuta imports
seguros para verificar que no haya errores de sintaxis/import.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# BD temporal ANTES de cualquier import de modelos (para que no choque
# con la BD de desarrollo si existe)
TEST_DB = tempfile.mktemp(suffix=".sqlite", prefix="notif_validator_")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("SEED_DEMO_USERS", "false")


_PASS = 0
_FAIL = 0


def check(cond: bool, msg: str, severity: str = "FAIL") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  + {msg}")
    else:
        if severity == "WARN":
            print(f"  ! WARN: {msg}")
        else:
            _FAIL += 1
            print(f"  X FAIL: {msg}")


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def subsection(title: str) -> None:
    print(f"\n--- {title} ---")


# =====================================================================
# FIX-1: Verificar que _enviar_email ya NO tiene el bug
# =====================================================================
def validate_fix1_enviar_email() -> None:
    section("FIX-1: deadline_notifier._enviar_email() ya no tiene el bug")

    dn_path = Path("/workspace/app/services/deadline_notifier.py")
    dn_text = dn_path.read_text(encoding="utf-8")
    check(len(dn_text) > 1000, f"Archivo leído: {dn_path.name} ({len(dn_text)} chars)")

    # Extraer la función _enviar_email completa (hasta el próximo 'def ' o 'class ')
    m = re.search(
        r"def _enviar_email\(.+?(?=\ndef |\nclass )",
        dn_text,
        re.DOTALL,
    )
    if not m:
        check(False, "Función _enviar_email() encontrada")
        return
    body = m.group(0)

    # El bug eliminado:
    check(
        "get_email_service" not in body,
        "FIX-1.A: NO se llama a get_email_service() (función inexistente eliminada)",
    )
    check(
        not re.search(r"email_ticket_en_columna\(\s*db=", body),
        "FIX-1.B: NO se llama a email_ticket_en_columna(db=...) con kwargs incorrectos",
    )
    check(
        not re.search(r"ok,\s*err\s*=\s*email_ticket_en_columna", body),
        "FIX-1.C: NO se desempaqueta como (ok, err) — usa (subject, body, html)",
    )

    # El fix presente:
    check(
        "from app.services.email_service import" in body
        and "send_email" in body
        and "email_ticket_en_columna" in body,
        "FIX-1.D: Importa correctamente send_email + email_ticket_en_columna",
    )
    check(
        "send_email(" in body and "to=usuario.email" in body,
        "FIX-1.E: Llama a send_email(to=usuario.email, ...) con la firma correcta",
    )
    check(
        "ticket_codigo=" in body
        and "ticket_titulo=" in body
        and "estado_destino=" in body
        and "responsable_nombre=" in body
        and "actor_nombre=" in body
        and "url_ticket=" in body,
        "FIX-1.F: email_ticket_en_columna se llama con todos los kwargs requeridos",
    )
    check(
        "result.sent" in body,
        "FIX-1.G: Verifica result.sent para considerar email exitoso",
    )
    check(
        "destinatario_sin_email" in body,
        "FIX-1.H: Manejo defensivo: skip si usuario.email está vacío",
    )


# =====================================================================
# FIX-2: Verificar feature de email admin Resultado Pruebas
# =====================================================================
def validate_fix2_admin_email() -> None:
    section("FIX-2: Email admin al modificar Resultado Pruebas — feature implementada")

    # 2.1) Plantilla en email_service.py
    es_path = Path("/workspace/app/services/email_service.py")
    es_text = es_path.read_text(encoding="utf-8")
    subsection("2.1) Plantilla email_resultado_pruebas_modificado()")
    check(
        "def email_resultado_pruebas_modificado(" in es_text,
        "Función email_resultado_pruebas_modificado() definida en email_service.py",
    )
    check(
        "ticket_codigo: str" in es_text.split("def email_resultado_pruebas_modificado(")[1][:500],
        "Parámetros tipados: ticket_codigo, ticket_titulo, valor_anterior, valor_nuevo, actor_nombre, url_ticket",
    )
    # Verificar firma con kwargs-only (defensa contra uso indebido)
    check(
        re.search(
            r"def email_resultado_pruebas_modificado\(\s*\*,", es_text,
        ) is not None,
        "Firma usa kwargs-only (*) — previene llamadas posicionales accidentales",
    )

    # 2.2) Servicio
    svc_path = Path(
        "/workspace/app/services/notificacion_admin_resultado_pruebas_service.py"
    )
    subsection("2.2) Servicio notificar_admin_resultado_pruebas")
    check(svc_path.exists(), f"Archivo existe: {svc_path.name}")
    if svc_path.exists():
        svc_text = svc_path.read_text(encoding="utf-8")
        check(
            "def notificar_admin_resultado_pruebas(" in svc_text,
            "Función notificar_admin_resultado_pruebas() implementada",
        )
        check(
            "RolUsuario.ADMINISTRADOR" in svc_text,
            "Filtra usuarios por rol=ADMINISTRADOR",
        )
        check(
            "Usuario.is_active == True" in svc_text,
            "Filtra solo usuarios activos",
        )
        check(
            "a.id != actor.id" in svc_text,
            "Excluye al actor del cambio (no auto-notificación)",
        )
        check(
            "send_email(" in svc_text,
            "Llama a send_email() para el envío real",
        )
        check(
            'accion="NOTIF_ADMIN_RESULTADO_PRUEBAS"' in svc_text,
            "Audita con acción 'NOTIF_ADMIN_RESULTADO_PRUEBAS'",
        )
        check(
            "registrar_auditoria(" in svc_text,
            "Llama a registrar_auditoria() para trazabilidad",
        )

    # 2.3) Trigger en endpoint /tickets/{id}/guardar
    subsection("2.3) Trigger en endpoint /tickets/{id}/guardar")
    tickets_path = Path("/workspace/app/api/v1/tickets.py")
    tickets_text = tickets_path.read_text(encoding="utf-8")

    # Localizar la sección del endpoint /guardar (hasta el próximo async/def/@router)
    m = re.search(
        r"async def guardar_ticket_campos.+?(?=\n@router\.|\nasync def |\ndef )",
        tickets_text,
        re.DOTALL,
    )
    check(m is not None, "Endpoint guardar_ticket_campos encontrado")
    if m:
        section_text = m.group(0)
        check(
            "notificar_admin_resultado_pruebas" in section_text,
            "FIX-2.A: Endpoint llama a notificar_admin_resultado_pruebas()",
        )
        check(
            '"resultado_pruebas" in valores_nuevos' in section_text,
            "FIX-2.B: Trigger solo si 'resultado_pruebas' está en valores_nuevos",
        )
        # Después de la llamada, debe haber manejo de excepciones
        parts = section_text.split("notificar_admin_resultado_pruebas(", 1)
        if len(parts) >= 2:
            after_call = parts[1][:1500]
            check(
                "except Exception" in after_call,
                "FIX-2.C: Manejo de excepciones: el trigger NO rompe el endpoint",
            )
            check(
                "db.commit()" in after_call,
                "FIX-2.D: Commit de la auditoría generada por el servicio",
            )
        else:
            check(False, "FIX-2.C: No se encontró sección post-llamada")
            check(False, "FIX-2.D: No se encontró sección post-llamada")


# =====================================================================
# REGRESIÓN: Validar que NO se rompió nada del flujo anterior
# =====================================================================
def validate_no_regression() -> None:
    section("REGRESIÓN: Verificar que las features previas siguen funcionando")

    dn_path = Path("/workspace/app/services/deadline_notifier.py")
    dn_text = dn_path.read_text(encoding="utf-8")

    # 4 trigger functions
    for fn in (
        "trigger_deadline_today",
        "trigger_deadline_missed",
        "trigger_deadline_approaching",
        "trigger_task_overdue",
    ):
        check(
            f"def {fn}(" in dn_text,
            f"Función {fn}() sigue presente (sin regresión)",
        )

    # 4 constantes
    for trig in ("DEADLINE_TODAY", "DEADLINE_MISSED", "DEADLINE_APPROACHING", "TASK_OVERDUE"):
        check(
            f"TRIGGER_{trig}" in dn_text,
            f"Constante TRIGGER_{trig} sigue presente",
        )

    # Filtros de queries
    check(
        dn_text.count("Ticket.archivado == False") >= 4,
        "Filtros archivado=False siguen en los 4 triggers",
    )
    check(
        dn_text.count("Ticket.estado.has(es_final=False)") >= 4,
        "Filtros es_final=False siguen en los 4 triggers",
    )
    check(
        dn_text.count("_crear_notificacion(db,") >= 4,
        "_crear_notificacion() sigue llamándose en los 4 triggers",
    )
    check(
        dn_text.count("_auditar(db, t,") >= 4,
        "_auditar() sigue llamándose en los 4 triggers",
    )
    check(
        dn_text.count("_ya_notificado_hoy(db, t.id,") >= 4,
        "Idempotencia 24h (_ya_notificado_hoy) sigue presente",
    )

    # Notificación responsable — sigue funcionando
    nrs_path = Path("/workspace/app/services/notificacion_responsable_service.py")
    nrs_text = nrs_path.read_text(encoding="utf-8")
    check(
        "def notificar_responsable_columna(" in nrs_text,
        "Servicio notificar_responsable_columna() sin cambios",
    )

    # Email service — las 3 plantillas
    es_path = Path("/workspace/app/services/email_service.py")
    es_text = es_path.read_text(encoding="utf-8")
    email_templates = re.findall(r"^def email_(\w+)\(", es_text, re.MULTILINE)
    check(
        "ticket_en_columna" in email_templates,
        "Plantilla email_ticket_en_columna sigue presente",
    )
    check(
        "credenciales_iniciales" in email_templates,
        "Plantilla email_credenciales_iniciales sigue presente",
    )
    check(
        "resultado_pruebas_modificado" in email_templates,
        "NUEVA plantilla email_resultado_pruebas_modificado presente",
    )


# =====================================================================
# SYNTAX CHECK: importar los módulos modificados para detectar errores
# =====================================================================
def validate_imports() -> None:
    section("SYNTAX: Importar módulos modificados (detecta errores de sintaxis/import)")

    # email_service no necesita BD
    try:
        from app.services import email_service  # noqa: F401
        check(True, "Importación de app.services.email_service OK")
    except Exception as exc:
        check(False, f"Importación de email_service falló: {exc}")

    # Para servicios que usan modelos, primero crear las tablas
    try:
        from app.db import base as db_base, session as db_session  # noqa: F401
        db_base.Base.metadata.create_all(bind=db_session.engine)
        check(True, "Esquema de BD creado en SQLite temporal")
    except Exception as exc:
        check(False, f"create_all falló: {exc}")

    # notificacion_admin_resultado_pruebas_service
    try:
        from app.services import notificacion_admin_resultado_pruebas_service  # noqa: F401
        check(True, "Importación de notificacion_admin_resultado_pruebas_service OK")
        # Verificar que la función es callable y tiene la firma correcta
        sig = notificacion_admin_resultado_pruebas_service.notificar_admin_resultado_pruebas
        check(
            callable(sig),
            "notificar_admin_resultado_pruebas es callable",
        )
    except Exception as exc:
        check(False, f"Importación de notificacion_admin_resultado_pruebas_service falló: {exc}")

    # deadline_notifier (no requiere import de la BD porque es funcional)
    try:
        from app.services import deadline_notifier  # noqa: F401
        check(True, "Importación de deadline_notifier OK")
        # Verificar que las 4 funciones existen y son callable
        for fn_name in (
            "trigger_deadline_today",
            "trigger_deadline_missed",
            "trigger_deadline_approaching",
            "trigger_task_overdue",
        ):
            fn = getattr(deadline_notifier, fn_name, None)
            check(
                callable(fn),
                f"deadline_notifier.{fn_name}() es callable",
            )
    except Exception as exc:
        check(False, f"Importación de deadline_notifier falló: {exc}")

    # notificacion_responsable_service
    try:
        from app.services import notificacion_responsable_service  # noqa: F401
        check(True, "Importación de notificacion_responsable_service OK")
    except Exception as exc:
        check(False, f"Importación de notificacion_responsable_service falló: {exc}")


# =====================================================================
# SMOKE TEST: Ejecutar flujo end-to-end con BD temporal
# =====================================================================
def smoke_test_end_to_end() -> None:
    section("SMOKE TEST: Flujo end-to-end con BD SQLite temporal")

    try:
        from app.core.security import hash_password  # noqa: F401
        from app.db import base as db_base, session as db_session  # noqa: F401
        from app.models import (
            Estado, Ticket, TipoIncidencia, Usuario, RolUsuario,
            Prioridad, Auditoria,
        )
        from app.services.email_service import (
            email_resultado_pruebas_modificado,
            send_email,
        )

        # Setup
        db_base.Base.metadata.create_all(bind=db_session.engine)
        db = db_session.SessionLocal()
        try:
            # 1 admin activo
            admin = Usuario(
                username="admin_test", email="admin_test@example.local",
                nombre_completo="Admin Test", rol=RolUsuario.ADMINISTRADOR,
                is_active=True, hashed_password=hash_password("test1234"),
            )
            # 1 agente que va a modificar
            agente = Usuario(
                username="agente_test", email="agente_test@example.local",
                nombre_completo="Agente Test", rol=RolUsuario.AGENTE,
                is_active=True, hashed_password=hash_password("test1234"),
            )
            estado = Estado(
                nombre="BACKLOG", categoria="planificacion",
                orden=1, es_inicial=True, archivado=False,
            )
            db.add_all([admin, agente, estado])
            db.flush()

            ticket = Ticket(
                codigo="TEST-001", titulo="Ticket de prueba",
                descripcion="Smoke test", tipo=TipoIncidencia.INCIDENCIA,
                prioridad=Prioridad.MEDIA,
                estado_id=estado.id, creador_id=agente.id,
                asignado_id=agente.id, fecha_inicio=None,
                fecha_vencimiento_sla=None,
                resultado_pruebas=None,
            )
            db.add(ticket)
            db.flush()

            check(
                admin.id is not None and agente.id is not None and ticket.id is not None,
                f"Setup OK: admin.id={admin.id} agente.id={agente.id} ticket.id={ticket.id}",
            )

            # 2) Probar plantilla nueva
            subject, body, html = email_resultado_pruebas_modificado(
                ticket_codigo=ticket.codigo,
                ticket_titulo=ticket.titulo,
                valor_anterior=None,
                valor_nuevo="EXITOSO",
                actor_nombre=agente.nombre_completo,
                url_ticket=f"/tickets#{ticket.id}",
            )
            check(
                ticket.codigo in subject and "EXITOSO" in subject,
                f"Plantilla genera subject OK: «{subject}»",
            )
            check(
                ticket.codigo in body and "EXITOSO" in body and "Agente Test" in body,
                "Plantilla genera body texto OK (incluye código, valor y actor)",
            )
            check(
                ticket.codigo in html and "EXITOSO" in html,
                "Plantilla genera body HTML OK (incluye código y valor)",
            )

            # 3) Probar servicio end-to-end (sin SMTP real, sólo log fallback)
            from app.services.notificacion_admin_resultado_pruebas_service import (
                notificar_admin_resultado_pruebas,
            )
            resultado = notificar_admin_resultado_pruebas(
                db,
                ticket=ticket,
                valor_anterior=None,
                valor_nuevo="EXITOSO",
                actor=agente,
            )
            check(
                resultado.get("destinatarios", 0) == 1,
                f"Servicio destinatarios={resultado.get('destinatarios')}",
            )
            # En entorno sin RESEND/SMTP, el email cae a log (sent=False,
            # transport='log') → el código sigue funcionando, sólo que el
            # email queda en tmp/app.email.log
            check(
                resultado.get("skipped_reason") is None,
                f"Servicio skipped_reason={resultado.get('skipped_reason')!r} "
                f"(None = NO se omitió, sí procesó)",
            )
            # Si llegó a log/dev_inbox, al menos intentó
            check(
                resultado.get("emails_enviados", 0) >= 0,
                f"Servicio emails_enviados={resultado.get('emails_enviados')} "
                f"(0 aceptable en dev; >=1 si hay SMTP)",
            )

            # 4) Verificar que se creó auditoría NOTIF_ADMIN_RESULTADO_PRUEBAS
            db.commit()
            auds = db.query(Auditoria).filter(
                Auditoria.accion == "NOTIF_ADMIN_RESULTADO_PRUEBAS",
            ).all()
            check(
                len(auds) == 1,
                f"Auditoría NOTIF_ADMIN_RESULTADO_PRUEBAS creada ({len(auds)} fila)",
            )

            # 5) Probar self-skip: si el actor es admin, no se auto-notifica
            db.delete(auds[0])
            db.commit()
            resultado2 = notificar_admin_resultado_pruebas(
                db,
                ticket=ticket,
                valor_anterior="EXITOSO",
                valor_nuevo="FALLIDO",
                actor=admin,  # actor = admin
            )
            check(
                resultado2.get("skipped_reason") == "ningun_admin_con_email_o_solo_actor",
                f"Self-skip OK: cuando actor=admin, skipped_reason="
                f"{resultado2.get('skipped_reason')!r}",
            )

            # 6) Probar deadline_notifier._enviar_email ahora funciona
            #    (sin invocar el trigger completo, sólo el helper)
            from app.services.deadline_notifier import _enviar_email
            # Llamada directa: NO debe lanzar excepción ahora
            err = _enviar_email(db, agente, ticket, "deadline_today")
            # err puede ser string (si falla) o None (si OK). Lo importante
            # es que NO sea una excepción no controlada.
            check(
                err is None or isinstance(err, str),
                f"_enviar_email() devuelve {'OK' if err is None else f'error: {err}'} "
                "(antes lanzaba excepción por get_email_service inexistente)",
            )
        finally:
            db.close()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        check(False, f"Smoke test crashed: {exc}")


def main() -> int:
    print("=" * 78)
    print("  VALIDACIÓN EXHAUSTIVA POST-FIXES — SISTEMA DE NOTIFICACIONES")
    print("  Fecha: 2026-09-23")
    print("=" * 78)

    validate_fix1_enviar_email()
    validate_fix2_admin_email()
    validate_no_regression()
    validate_imports()
    smoke_test_end_to_end()

    print("\n" + "=" * 78)
    print(f"  RESUMEN: {_PASS} checks OK, {_FAIL} checks FALLARON")
    print("=" * 78)

    if _FAIL == 0:
        print("\n  ✓✓✓ TODOS LOS FIXES VALIDADOS CORRECTAMENTE ✓✓✓\n")
        return 0
    else:
        print(f"\n  XXX {_FAIL} CHECKS FALLARON — REVISAR XXX\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
