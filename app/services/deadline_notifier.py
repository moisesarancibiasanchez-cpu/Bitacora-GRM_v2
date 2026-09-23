"""
FEATURE 2 — Servicio de notificaciones por Deadline.

Implementa los 4 triggers estilo Bitrix24 para alertas de SLA:

    1. Deadline today       (vencen hoy)
    2. Deadline missed      (ya vencidas)
    3. Deadline approaching (próximas a vencer, N horas antes)
    4. Task is overdue      (vencidas y NO completas)

Cada trigger:
    - Identifica los tickets aplicables con una query SQL específica.
    - Genera UNA Notificación in-app POR CADA responsable (creador +
      asignado) — sin duplicar si coincide.
    - Envía UN email por destinatario (en producción: vía email_service
      Resend; en dev: vía Dev Inbox).
    - Inserta UNA fila en ``auditoria`` por ticket con tipo
      ``deadline_trigger`` (es un evento del sistema, no de un usuario).

Uso:
    Llamar desde Celery Beat (cron):
        - ``revisar_deadlines_diario()``  → corre todos los días a las 8:00
        - ``revisar_deadlines_horario()``  → corre cada hora (sólo ``approaching``)

O desde CLI para forzar:
    ``python -m app.services.deadline_notifier`` → ejecuta los 4 triggers
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.auditoria import Auditoria
from app.models.ticket import Ticket
from app.models.usuario import Usuario
from app.models.watch import Notificacion

logger = logging.getLogger(__name__)


# ============================================================================
# Catálogo de triggers (nombre_canónico → descripción)
# ============================================================================
TRIGGER_DEADLINE_TODAY = "deadline_today"
TRIGGER_DEADLINE_MISSED = "deadline_missed"
TRIGGER_DEADLINE_APPROACHING = "deadline_approaching"
TRIGGER_TASK_OVERDUE = "task_overdue"

TRIGGERS_TODOS = [
    TRIGGER_DEADLINE_TODAY,
    TRIGGER_DEADLINE_MISSED,
    TRIGGER_DEADLINE_APPROACHING,
    TRIGGER_TASK_OVERDUE,
]

TRIGGER_DESCRIPCIONES = {
    TRIGGER_DEADLINE_TODAY: "Vencen hoy",
    TRIGGER_DEADLINE_MISSED: "Vencidas",
    TRIGGER_DEADLINE_APPROACHING: "Próximas a vencer (4h)",
    TRIGGER_TASK_OVERDUE: "Vencidas y no completas",
}


# ============================================================================
# Estructura de resultados (para retorno / logging)
# ============================================================================
@dataclass
class ResultadoTrigger:
    trigger: str
    tickets_encontrados: int = 0
    notificaciones_creadas: int = 0
    emails_enviados: int = 0
    errores: List[str] = field(default_factory=list)
    tickets: List[int] = field(default_factory=list)


# ============================================================================
# Helpers
# ============================================================================
def _destinatarios_de_ticket(db: Session, ticket: Ticket) -> List[Usuario]:
    """Devuelve creador + asignado + miembros, sin duplicados y sólo
    los que estén activos."""
    ids: Set[int] = set()
    if ticket.creador_id:
        ids.add(ticket.creador_id)
    if ticket.asignado_id:
        ids.add(ticket.asignado_id)
    for m in (ticket.miembros or []):
        if m.is_active:
            ids.add(m.id)
    if not ids:
        return []
    return db.query(Usuario).filter(
        Usuario.id.in_(ids),
        Usuario.is_active == True,  # noqa: E712
    ).all()


def _ya_notificado_hoy(db: Session, ticket_id: int, trigger: str) -> bool:
    """Idempotencia: si YA hay una auditoría con este trigger en las
    últimas 24h para este ticket, NO lo notificamos de nuevo. Evita
    ráfagas si Celery Beat corre el job múltiples veces al día."""
    hace_24h = datetime.utcnow() - timedelta(hours=24)
    existe = db.query(Auditoria).filter(
        Auditoria.ticket_id == ticket_id,
        Auditoria.accion == f"deadline_trigger:{trigger}",
        Auditoria.created_at >= hace_24h,
    ).first()
    return existe is not None


def _crear_notificacion(
    db: Session,
    usuario: Usuario,
    ticket: Ticket,
    trigger: str,
) -> None:
    """Inserta una notificación in-app para ``usuario`` sobre ``ticket``.

    El campo ``tipo`` se aprovecha para distinguir visualmente:
        - deadline_today: icono reloj amarillo
        - deadline_missed: icono exclamación rojo
        - deadline_approaching: icono campana ámbar
        - task_overdue: icono círculo rojo
    """
    notif = Notificacion(
        usuario_id=usuario.id,
        ticket_id=ticket.id,
        tipo=trigger,
        titulo=f"[{TRIGGER_DESCRIPCIONES.get(trigger, trigger)}] {ticket.codigo}",
        mensaje=_cuerpo_notificacion(ticket, trigger),
        leida=False,
    )
    db.add(notif)


def _cuerpo_notificacion(ticket: Ticket, trigger: str) -> str:
    """Genera el cuerpo legible de la notificación."""
    titulo = (ticket.titulo or "")[:100]
    if trigger == TRIGGER_DEADLINE_TODAY:
        return f"Tu ticket '{titulo}' vence hoy."
    if trigger == TRIGGER_DEADLINE_MISSED:
        return f"Tu ticket '{titulo}' está vencido desde el {ticket.fecha_vencimiento_sla.strftime('%Y-%m-%d') if ticket.fecha_vencimiento_sla else '?'}."
    if trigger == TRIGGER_DEADLINE_APPROACHING:
        return f"Tu ticket '{titulo}' vence en menos de 4 horas."
    if trigger == TRIGGER_TASK_OVERDUE:
        return f"Tu ticket '{titulo}' está vencido y aún no se ha completado."
    return f"Trigger '{trigger}' aplicado a '{titulo}'."


def _enviar_email(db: Session, usuario: Usuario, ticket: Ticket, trigger: str) -> Optional[str]:
    """Envía un email de alerta de SLA al usuario.

    Retorna ``None`` si el email se entregó correctamente, o un mensaje
    breve de error si falló (registrado en ``ResultadoTrigger.errores``).

    Notas de implementación
    -----------------------
    - Importación LAZY de ``email_service`` para evitar ciclos de import.
    - Reusa la plantilla ``email_ticket_en_columna()`` (ya validada por
      el flujo "responsable al mover tarjeta") inyectando el nombre del
      trigger como ``estado_destino`` para que el asunto y el cuerpo
      reflejen el tipo de alerta (``"Alerta de SLA: Vencen hoy"`` etc.).
    - Pasa por la cadena completa de ``send_email()``:
      Resend HTTP API → SMTP → log + Dev Inbox (fallback).
    - Si el usuario no tiene email configurado, se omite silenciosamente.
    """
    if not getattr(usuario, "email", None):
        return "destinatario_sin_email"

    try:
        from app.services.email_service import email_ticket_en_columna, send_email

        trigger_label = TRIGGER_DESCRIPCIONES.get(trigger, trigger)
        url_ticket = f"/tickets#{ticket.id}"
        # Reusamos plantilla existente con semántica adaptada:
        # - estado_origen: irrelevante para alertas de SLA → "(sistema)"
        # - estado_destino: nombre legible del trigger para que el
        #   asunto del email quede autoexplicativo
        # - actor_nombre: el "remitente" es el sistema, no un humano
        subject, body, html = email_ticket_en_columna(
            ticket_codigo=ticket.codigo,
            ticket_titulo=ticket.titulo or "(sin título)",
            estado_origen="(sistema)",
            estado_destino=f"Alerta de SLA: {trigger_label}",
            responsable_nombre=usuario.nombre_completo or usuario.username,
            actor_nombre="Sistema (Deadline Notifier)",
            url_ticket=url_ticket,
        )
        # Prefijamos el asunto con [SLA] para que el destinatario
        # reconozca el email como alerta automática (no movimiento manual).
        result = send_email(
            to=usuario.email,
            subject=f"[SLA] {subject}",
            body=body,
            html_body=html,
        )
        if not result.sent:
            return f"email_no_entregado: {result.transport} ({result.detail or 'sin detalle'})"
        return None
    except Exception as exc:
        logger.warning(
            "[deadline] Error enviando email a %s: %s",
            getattr(usuario, "email", "?"), exc,
        )
        return f"excepcion: {exc}"


def _auditar(db: Session, ticket: Ticket, trigger: str, n_notifs: int, n_emails: int) -> None:
    """Inserta fila de auditoría con la marca del trigger ejecutado."""
    aud = Auditoria(
        ticket_id=ticket.id,
        usuario_id=None,  # evento del sistema
        accion=f"deadline_trigger:{trigger}",
        valor_anterior=None,
        valor_nuevo={
            "trigger": trigger,
            "notificaciones_creadas": n_notifs,
            "emails_enviados": n_emails,
            "ts": datetime.utcnow().isoformat(),
        },
        comentario=f"Trigger {trigger} ejecutado automáticamente.",
        ip_origen="system:deadline_notifier",
    )
    db.add(aud)


# ============================================================================
# Funciones principales (un trigger cada una)
# ============================================================================
def trigger_deadline_today(db: Session) -> ResultadoTrigger:
    """Trigger 1: tickets que vencen HOY (fecha_vencimiento_sla en [00:00, 23:59:59])."""
    res = ResultadoTrigger(trigger=TRIGGER_DEADLINE_TODAY)
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_fin = hoy_inicio + timedelta(days=1)
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.archivado == False,  # noqa: E712
            Ticket.fecha_vencimiento_sla >= hoy_inicio,
            Ticket.fecha_vencimiento_sla < hoy_fin,
            # Excluir tickets cerrados (estado.es_final == True)
            Ticket.estado.has(es_final=False),
        )
        .all()
    )
    for t in tickets:
        if _ya_notificado_hoy(db, t.id, TRIGGER_DEADLINE_TODAY):
            continue
        destinatarios = _destinatarios_de_ticket(db, t)
        if not destinatarios:
            continue
        n_notifs = 0
        n_emails = 0
        for u in destinatarios:
            _crear_notificacion(db, u, t, TRIGGER_DEADLINE_TODAY)
            n_notifs += 1
            err = _enviar_email(db, u, t, TRIGGER_DEADLINE_TODAY)
            if err is None:
                n_emails += 1
            else:
                res.errores.append(f"ticket {t.id} → {u.email}: {err}")
        _auditar(db, t, TRIGGER_DEADLINE_TODAY, n_notifs, n_emails)
        res.tickets_encontrados += 1
        res.notificaciones_creadas += n_notifs
        res.emails_enviados += n_emails
        res.tickets.append(t.id)
    db.commit()
    return res


def trigger_deadline_missed(db: Session) -> ResultadoTrigger:
    """Trigger 2: tickets vencidos (fecha_vencimiento_sla < hoy)."""
    res = ResultadoTrigger(trigger=TRIGGER_DEADLINE_MISSED)
    ahora = datetime.utcnow()
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.archivado == False,  # noqa: E712
            Ticket.fecha_vencimiento_sla < ahora,
            Ticket.estado.has(es_final=False),
        )
        .all()
    )
    for t in tickets:
        if _ya_notificado_hoy(db, t.id, TRIGGER_DEADLINE_MISSED):
            continue
        destinatarios = _destinatarios_de_ticket(db, t)
        if not destinatarios:
            continue
        n_notifs = 0
        n_emails = 0
        for u in destinatarios:
            _crear_notificacion(db, u, t, TRIGGER_DEADLINE_MISSED)
            n_notifs += 1
            err = _enviar_email(db, u, t, TRIGGER_DEADLINE_MISSED)
            if err is None:
                n_emails += 1
        _auditar(db, t, TRIGGER_DEADLINE_MISSED, n_notifs, n_emails)
        res.tickets_encontrados += 1
        res.notificaciones_creadas += n_notifs
        res.emails_enviados += n_emails
        res.tickets.append(t.id)
    db.commit()
    return res


def trigger_deadline_approaching(db: Session, ventana_horas: int = 4) -> ResultadoTrigger:
    """Trigger 3: tickets que vencen en las próximas N horas."""
    res = ResultadoTrigger(trigger=TRIGGER_DEADLINE_APPROACHING)
    ahora = datetime.utcnow()
    limite = ahora + timedelta(hours=ventana_horas)
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.archivado == False,  # noqa: E712
            Ticket.fecha_vencimiento_sla >= ahora,
            Ticket.fecha_vencimiento_sla < limite,
            Ticket.estado.has(es_final=False),
        )
        .all()
    )
    for t in tickets:
        if _ya_notificado_hoy(db, t.id, TRIGGER_DEADLINE_APPROACHING):
            continue
        destinatarios = _destinatarios_de_ticket(db, t)
        if not destinatarios:
            continue
        n_notifs = 0
        n_emails = 0
        for u in destinatarios:
            _crear_notificacion(db, u, t, TRIGGER_DEADLINE_APPROACHING)
            n_notifs += 1
            err = _enviar_email(db, u, t, TRIGGER_DEADLINE_APPROACHING)
            if err is None:
                n_emails += 1
        _auditar(db, t, TRIGGER_DEADLINE_APPROACHING, n_notifs, n_emails)
        res.tickets_encontrados += 1
        res.notificaciones_creadas += n_notifs
        res.emails_enviados += n_emails
        res.tickets.append(t.id)
    db.commit()
    return res


def trigger_task_overdue(db: Session) -> ResultadoTrigger:
    """Trigger 4: tickets vencidos Y que NO están en estado final.

    La diferencia con ``deadline_missed`` es que aquí SÓLO se notifica
    si el ticket aún tiene ``fecha_completado is None`` (no se cerró
    formalmente) — útil para recordar tickets 'olvidados'.
    """
    res = ResultadoTrigger(trigger=TRIGGER_TASK_OVERDUE)
    ahora = datetime.utcnow()
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.archivado == False,  # noqa: E712
            Ticket.fecha_vencimiento_sla < ahora,
            Ticket.fecha_completado.is_(None),
            Ticket.estado.has(es_final=False),
        )
        .all()
    )
    for t in tickets:
        if _ya_notificado_hoy(db, t.id, TRIGGER_TASK_OVERDUE):
            continue
        destinatarios = _destinatarios_de_ticket(db, t)
        if not destinatarios:
            continue
        n_notifs = 0
        n_emails = 0
        for u in destinatarios:
            _crear_notificacion(db, u, t, TRIGGER_TASK_OVERDUE)
            n_notifs += 1
            err = _enviar_email(db, u, t, TRIGGER_TASK_OVERDUE)
            if err is None:
                n_emails += 1
        _auditar(db, t, TRIGGER_TASK_OVERDUE, n_notifs, n_emails)
        res.tickets_encontrados += 1
        res.notificaciones_creadas += n_notifs
        res.emails_enviados += n_emails
        res.tickets.append(t.id)
    db.commit()
    return res


# ============================================================================
# Orquestador
# ============================================================================
def ejecutar_todos_los_triggers(db: Optional[Session] = None) -> Dict[str, ResultadoTrigger]:
    """Ejecuta los 4 triggers en secuencia. Usado por Celery Beat o CLI."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        resultados = {
            TRIGGER_DEADLINE_TODAY: trigger_deadline_today(db),
            TRIGGER_DEADLINE_MISSED: trigger_deadline_missed(db),
            TRIGGER_DEADLINE_APPROACHING: trigger_deadline_approaching(db),
            TRIGGER_TASK_OVERDUE: trigger_task_overdue(db),
        }
        for trig, r in resultados.items():
            logger.info(
                "[deadline:%s] tickets=%d notifs=%d emails=%d errores=%d",
                trig, r.tickets_encontrados, r.notificaciones_creadas,
                r.emails_enviados, len(r.errores),
            )
        return resultados
    finally:
        if close_db:
            db.close()


# ============================================================================
# CLI — permite correr manualmente
# ============================================================================
if __name__ == "__main__":  # pragma: no cover
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = ejecutar_todos_los_triggers()
    print(json.dumps(
        {
            t: {
                "tickets_encontrados": r.tickets_encontrados,
                "notificaciones_creadas": r.notificaciones_creadas,
                "emails_enviados": r.emails_enviados,
                "errores_count": len(r.errores),
                "primeros_errores": r.errores[:3],
            }
            for t, r in res.items()
        },
        indent=2, ensure_ascii=False,
    ))
