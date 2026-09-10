"""
Servicio de notificación al responsable de una columna del Kanban.

Cuando un ticket cae en un estado (columna) que tiene un usuario
``responsable_id`` configurado, este servicio:

1. Crea un registro ``Notificacion`` (in-app) para ese usuario.
2. Envía un email al responsable (vía ``EmailService``).
3. Loguea todo en la tabla ``auditoria`` como ``NOTIF_RESPONSABLE_COL``.

Si la columna no tiene responsable, o si el responsable no tiene email,
se omite la parte correspondiente (no es un error).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.estado import Estado
from app.models.ticket import Ticket
from app.models.usuario import Usuario
from app.models.watch import Notificacion
from app.services.email_service import (
    email_ticket_en_columna,
    send_email,
)


logger = logging.getLogger(__name__)


def notificar_responsable_columna(
    db: Session,
    *,
    ticket: Ticket,
    estado_destino: Estado,
    estado_origen_nombre: str,
    actor: Usuario,
    base_url: str = "",
) -> dict:
    """
    Notifica al responsable de la columna destino cuando un ticket cae
    en ella.

    Parameters
    ----------
    db : Session
        Sesión de SQLAlchemy.
    ticket : Ticket
        Ticket que se movió (debe tener ``codigo`` y ``titulo``).
    estado_destino : Estado
        Estado al que se movió el ticket (puede tener ``responsable_id``).
    estado_origen_nombre : str
        Nombre del estado anterior (para el mensaje).
    actor : Usuario
        Usuario que realizó el movimiento.
    base_url : str
        URL base para construir el link al ticket (opcional).

    Returns
    -------
    dict
        ``{"notif_created": bool, "email": {...}, "skipped_reason": str|None}``
    """
    responsable_id = getattr(estado_destino, "responsable_id", None)
    if not responsable_id:
        return {
            "notif_created": False,
            "email": None,
            "skipped_reason": "columna_sin_responsable",
        }

    responsable = (
        db.query(Usuario).filter(Usuario.id == responsable_id).first()
    )
    if not responsable or not responsable.is_active:
        return {
            "notif_created": False,
            "email": None,
            "skipped_reason": "responsable_inactivo_o_inexistente",
        }

    # No notificar al propio actor si coincide con el responsable.
    if responsable.id == actor.id:
        return {
            "notif_created": False,
            "email": None,
            "skipped_reason": "actor_es_responsable",
        }

    url = f"{base_url}/tickets" if base_url else "/tickets"
    url = f"{url}#ticket-{ticket.id}"

    # 1) Crear notificación in-app
    notif = Notificacion(
        usuario_id=responsable.id,
        tipo="estado",
        ticket_id=ticket.id,
        titulo=f"Ticket {ticket.codigo} en tu columna «{estado_destino.nombre}»",
        mensaje=(
            f"El usuario {actor.nombre_completo or actor.username} movió el "
            f"ticket «{ticket.titulo}» desde «{estado_origen_nombre}» a "
            f"«{estado_destino.nombre}», columna que tienes asignada como "
            f"responsable."
        ),
        url=url,
        leida=False,
        origen_usuario_id=actor.id,
    )
    db.add(notif)
    try:
        db.flush()
        notif_created = True
    except Exception as exc:
        logger.exception("[notif-resp] No se pudo crear Notificacion: %s", exc)
        db.rollback()
        notif_created = False

    # 2) Enviar email (no rompe el flujo si falla)
    email_info: dict = {"sent": False, "transport": "skipped"}
    if responsable.email:
        subject, body, html = email_ticket_en_columna(
            ticket_codigo=ticket.codigo,
            ticket_titulo=ticket.titulo,
            estado_origen=estado_origen_nombre,
            estado_destino=estado_destino.nombre,
            responsable_nombre=responsable.nombre_completo or responsable.username,
            actor_nombre=actor.nombre_completo or actor.username,
            url_ticket=url,
        )
        result = send_email(
            to=responsable.email,
            subject=subject,
            body=body,
            html_body=html,
        )
        email_info = {
            "sent": result.sent,
            "transport": result.transport,
            "to": result.to,
            "detail": result.detail,
        }

    # 3) Auditoría (best-effort, no rompe si la tabla no tiene la acción)
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=ticket.id,
            usuario_id=actor.id,
            accion="NOTIF_RESPONSABLE_COL",
            valor_nuevo={
                "estado_destino": estado_destino.nombre,
                "responsable_id": responsable.id,
                "responsable_username": responsable.username,
                "email_sent": email_info.get("sent", False),
                "email_transport": email_info.get("transport", "skipped"),
                "notif_id": notif.id if notif_created else None,
            },
            comentario=(
                f"Notificación enviada al responsable de la columna "
                f"«{estado_destino.nombre}» (usuario: {responsable.username})."
            ),
            commit=False,
        )
    except Exception as exc:
        logger.debug("[notif-resp] auditoría opcional: %s", exc)

    return {
        "notif_created": notif_created,
        "email": email_info,
        "skipped_reason": None,
    }
