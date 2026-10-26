"""Servicio Kanban: validación de transiciones y movimiento de tickets.

Reglas ITSM obligatorias:
1. Verificar que existe una transición válida entre el estado actual y el destino.
2. Verificar que el rol del usuario satisface el `rol_requerido`.
3. Verificar campos obligatorios (ej. comentario) si la transición lo exige.
4. Actualizar el ticket.
5. Insertar OBLIGATORIAMENTE un registro de auditoría.
6. Disparar tareas asíncronas en Celery (SLA + notificaciones).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.estado import Estado
from app.models.ticket import Ticket
from app.models.transicion import Transicion
from app.models.auditoria import AuditoriaEvento, TipoEvento
from app.models.usuario import Usuario
from app.tasks.kanban_tasks import recalcular_sla_ticket, notificar_cambio_estado


class TransicionInvalidaError(HTTPException):
    """Excepción 422: la transición solicitada no existe o no es legal."""
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


class PermisoInsuficienteError(HTTPException):
    """Excepción 403: el usuario no tiene el rol requerido para esta transición."""
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def obtener_columnas_kanban(db: Session) -> list[dict[str, Any]]:
    """Retorna todas las columnas (estados activos) ordenadas con sus tickets."""
    estados = (
        db.query(Estado)
        .filter(Estado.activo.is_(True))
        .order_by(Estado.orden.asc(), Estado.id.asc())
        .all()
    )
    columnas: list[dict[str, Any]] = []
    for est in estados:
        tickets = (
            db.query(Ticket)
            .filter(Ticket.estado_id == est.id)
            .order_by(Ticket.posicion.asc(), Ticket.id.asc())
            .all()
        )
        columnas.append({
            "id": est.id,
            "nombre": est.nombre,
            "descripcion": est.descripcion,
            "orden": est.orden,
            "categoria": est.categoria.value,
            "color": est.color,
            "es_inicial": est.es_inicial,
            "es_final": est.es_final,
            "tickets": [_serializar_ticket_resumido(t) for t in tickets],
        })
    return columnas


def _serializar_ticket_resumido(t: Ticket) -> dict[str, Any]:
    return {
        "id": t.id,
        "estado_id": t.estado_id,
        "codigo": t.codigo,
        "titulo": t.titulo,
        "prioridad": t.prioridad.value,
        "asignado_id": t.asignado_id,
        "posicion": t.posicion,
        "fecha_vencimiento_sla": t.fecha_vencimiento_sla.isoformat() if t.fecha_vencimiento_sla else None,
        "sla_cumplido": t.sla_cumplido,
    }


def mover_ticket(
    db: Session,
    ticket_id: int,
    estado_destino_id: int,
    usuario: Usuario,
    nueva_posicion: int = 0,
    comentario: str = "",
) -> dict[str, Any]:
    """Mueve un ticket a un nuevo estado. Valida reglas ITSM obligatorias.

    Retorna el fragmento HTML renderizado del ticket (para HTMX).
    Lanza HTTPException 404/403/422 si la operación no es legal.
    """
    # 1. Cargar ticket y estado actual
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no existe")

    estado_origen = ticket.estado
    if not estado_origen:
        raise HTTPException(status_code=500, detail="Ticket sin estado asociado")

    if estado_origen.id == estado_destino_id:
        # No-op: solo actualizar posición dentro de la misma columna.
        ticket.posicion = nueva_posicion
        db.commit()
        return _serializar_ticket_resumido(ticket)

    # 2. Verificar que el estado destino existe y está activo
    estado_destino = db.get(Estado, estado_destino_id)
    if not estado_destino or not estado_destino.activo:
        raise TransicionInvalidaError(
            f"Estado destino {estado_destino_id} no existe o no está activo"
        )

    # 3. Buscar la regla de transición legal
    transicion = (
        db.query(Transicion)
        .filter(
            Transicion.origen_id == estado_origen.id,
            Transicion.destino_id == estado_destino.id,
            Transicion.activo.is_(True),
        )
        .first()
    )
    if not transicion:
        raise TransicionInvalidaError(
            f"No existe transición legal de «{estado_origen.nombre}» a «{estado_destino.nombre}»"
        )

    # 4. Verificar permisos (rol)
    if not transicion.usuario_tiene_permiso(usuario.rol):
        raise PermisoInsuficienteError(
            f"Tu rol ({usuario.rol.value}) no tiene permiso para «{transicion.nombre or 'esta transición'}» "
            f"(rol requerido: {transicion.rol_requerido.value})"
        )

    # 5. Verificar campos obligatorios (comentario)
    if transicion.requiere_comentario and not comentario.strip():
        raise TransicionInvalidaError(
            "Esta transición requiere un comentario de justificación"
        )

    # 6. Aplicar cambio
    nombre_origen = estado_origen.nombre
    ticket.estado_id = estado_destino.id
    ticket.posicion = nueva_posicion
    ticket.updated_at = datetime.now(tz=timezone.utc)

    # 7. AUDITORÍA OBLIGATORIA
    evento = AuditoriaEvento(
        ticket_id=ticket.id,
        tipo=TipoEvento.ESTADO_CAMBIADO,
        actor_id=usuario.id,
        actor_username=usuario.username,
        valor_anterior=json.dumps({
            "estado_id": estado_origen.id,
            "estado_nombre": estado_origen.nombre,
            "posicion": ticket.posicion,
        }),
        valor_nuevo=json.dumps({
            "estado_id": estado_destino.id,
            "estado_nombre": estado_destino.nombre,
            "posicion": nueva_posicion,
        }),
        comentario=comentario,
    )
    db.add(evento)

    # 8. Si la transición lo solicita, recalcular SLA en background (Celery).
    if transicion.dispara_recalculo_sla:
        # apply_async para no bloquear el hilo principal de FastAPI.
        try:
            recalcular_sla_ticket.delay(ticket.id)
        except Exception:  # broker no disponible: la app sigue funcionando.
            pass
        # Notificación asíncrona
        try:
            notificar_cambio_estado.delay(ticket.id, nombre_origen, estado_destino.nombre)
        except Exception:
            pass

    db.commit()
    db.refresh(ticket)

    return _serializar_ticket_resumido(ticket)
