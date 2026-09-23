"""
Servicio de notificación al Administrador cuando se modifica
``Resultado Pruebas`` en el detalle de un ticket.

Este servicio se activa desde el endpoint ``POST /tickets/{id}/guardar``
cuando el campo ``resultado_pruebas`` está dentro de los cambios
efectivos (``valores_nuevos``).

Comportamiento
--------------
1. Busca todos los usuarios con ``rol=ADMINISTRADOR`` y ``is_active=True``.
2. Omite al actor del cambio (no se auto-notifica).
3. Filtra los destinatarios que tengan ``email`` configurado.
4. Construye el email con la plantilla
   ``email_resultado_pruebas_modificado()``.
5. Envía usando la cadena estándar
   (``send_email`` → Resend HTTP API → SMTP → log + Dev Inbox).
6. Audita como ``NOTIF_ADMIN_RESULTADO_PRUEBAS`` con metadatos del envío.

Best-effort: si el envío falla, el endpoint ``/guardar`` ya respondió
exitosamente al usuario (el cambio se persistió y auditó). El error de
email queda como warning en logs + entrada de auditoría.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.usuario import Usuario, RolUsuario
from app.services.email_service import (
    email_resultado_pruebas_modificado,
    send_email,
)


logger = logging.getLogger(__name__)


def notificar_admin_resultado_pruebas(
    db: Session,
    *,
    ticket: Ticket,
    valor_anterior: Optional[str],
    valor_nuevo: Optional[str],
    actor: Usuario,
    base_url: str = "",
) -> dict:
    """Notifica a todos los administradores activos del cambio en
    ``Resultado Pruebas``.

    Parameters
    ----------
    db : Session
        Sesión de SQLAlchemy.
    ticket : Ticket
        Ticket modificado (debe tener ``codigo`` y ``titulo``).
    valor_anterior : str | None
        Valor previo de ``resultado_pruebas`` (``None`` si estaba vacío).
    valor_nuevo : str | None
        Valor nuevo (``None`` si se vació).
    actor : Usuario
        Usuario que ejecutó el cambio.
    base_url : str
        Prefijo URL (opcional) para construir el link al ticket.

    Returns
    -------
    dict
        ``{
            "destinatarios": int,
            "emails_enviados": int,
            "errores": list[str],
            "skipped_reason": str | None,
        }``
    """
    # 1) Buscar administradores activos
    admins = (
        db.query(Usuario)
        .filter(
            Usuario.is_active == True,  # noqa: E712
            Usuario.rol == RolUsuario.ADMINISTRADOR,
        )
        .all()
    )

    if not admins:
        return {
            "destinatarios": 0,
            "emails_enviados": 0,
            "errores": [],
            "skipped_reason": "no_administradores_activos",
        }

    # 2) Excluir al actor (no se auto-notifica) y filtrar por email
    destinatarios = [
        a for a in admins
        if a.id != actor.id and getattr(a, "email", None)
    ]

    if not destinatarios:
        return {
            "destinatarios": 0,
            "emails_enviados": 0,
            "errores": [],
            "skipped_reason": "ningun_admin_con_email_o_solo_actor",
        }

    # 3) Construir contenido del email (una sola vez, se reutiliza)
    url = f"{base_url}/tickets" if base_url else "/tickets"
    url = f"{url}#ticket-{ticket.id}"

    subject, body, html = email_resultado_pruebas_modificado(
        ticket_codigo=ticket.codigo,
        ticket_titulo=ticket.titulo or "(sin título)",
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        actor_nombre=actor.nombre_completo or actor.username,
        url_ticket=url,
    )

    # 4) Enviar a cada admin (best-effort, no rompe si uno falla)
    enviados = 0
    errores: list[str] = []
    for admin in destinatarios:
        try:
            result = send_email(
                to=admin.email,
                subject=subject,
                body=body,
                html_body=html,
            )
            if result.sent:
                enviados += 1
            else:
                msg = (
                    f"{admin.username} <{admin.email}>: "
                    f"{result.transport} ({result.detail or 'sin detalle'})"
                )
                errores.append(msg)
                logger.warning(
                    "[notif-admin-resultado] Email NO entregado a %s: %s",
                    admin.email, msg,
                )
        except Exception as exc:
            errores.append(f"{admin.username} <{admin.email}>: excepcion {exc}")
            logger.exception(
                "[notif-admin-resultado] Excepción enviando a %s: %s",
                admin.email, exc,
            )

    # 5) Auditoría (best-effort, no rompe si la tabla no tiene la acción)
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=ticket.id,
            usuario_id=actor.id,
            accion="NOTIF_ADMIN_RESULTADO_PRUEBAS",
            valor_anterior={"resultado_pruebas": valor_anterior},
            valor_nuevo={
                "resultado_pruebas": valor_nuevo,
                "destinatarios": len(destinatarios),
                "emails_enviados": enviados,
                "transportes_ok": [
                    a.username for a in destinatarios
                    if getattr(a, "email", None)
                ][:enviados],
            },
            comentario=(
                f"Notificación a {enviados}/{len(destinatarios)} administrador(es) "
                f"por cambio en Resultado Pruebas: "
                f"«{valor_anterior or '(vacío)'}» → «{valor_nuevo or '(vacío)'}»."
            ),
            commit=False,
        )
    except Exception as exc:
        logger.debug(
            "[notif-admin-resultado] auditoría opcional: %s", exc,
        )

    return {
        "destinatarios": len(destinatarios),
        "emails_enviados": enviados,
        "errores": errores,
        "skipped_reason": None,
    }
