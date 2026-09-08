"""
Endpoints del módulo de Incidencias.
El más importante: PATCH /tickets/{id}/estado - recibe la señal de HTMX.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket
from app.models.usuario import Usuario
from app.schemas.ticket import (
    TicketCreate, TicketRead, CambioEstadoRequest, CambioEstadoResponse, ErrorResponse,
)
from app.services.ticket_service import (
    TicketService, TransicionInvalidaError, PermisoInsuficienteError,
)


router = APIRouter(prefix="/tickets", tags=["Incidencias"])


@router.get("", response_model=list[TicketRead])
def listar_tickets(
    estado_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todos los tickets (filtrable por estado)."""
    q = db.query(Ticket)
    if estado_id is not None:
        q = q.filter(Ticket.estado_id == estado_id)
    return q.order_by(Ticket.created_at.desc()).all()


@router.post("", response_model=TicketRead, status_code=201)
def crear_ticket(
    datos: TicketCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea un nuevo ticket (incidencia)."""
    service = TicketService(db)
    try:
        ticket = service.crear_ticket(
            datos=datos.model_dump(),
            usuario=usuario,
            ip_origen=request.client.host if request.client else None,
        )
        return ticket
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{ticket_id}", response_model=TicketRead)
def obtener_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Detalle de un ticket."""
    service = TicketService(db)
    ticket = service.obtener_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return ticket


# ===========================================================================
#  ENDPOINT PRINCIPAL: cambio de estado desde Kanban (drag & drop HTMX)
# ===========================================================================
@router.patch("/{ticket_id}/estado", response_class=HTMLResponse)
def cambiar_estado(
    ticket_id: int,
    body: CambioEstadoRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Cambia el estado de un ticket.
    - Valida la transición contra la tabla `transiciones_estado`.
    - Inserta en `historial_estados` y `auditorias`.
    - Dispara tareas Celery (no bloquea).
    - Devuelve SOLO el fragmento HTML de la tarjeta para HTMX (sin recargar página).
    - Si la validación falla, devuelve un HX-Trigger con el error y código 422
      para que HTMX muestre el toast y la tarjeta vuelva a su columna original.
    """
    service = TicketService(db)
    try:
        ticket, task_id = service.cambiar_estado(
            ticket_id=ticket_id,
            estado_destino_id=body.estado_id,
            usuario=usuario,
            comentario=body.comentario,
            orden=body.orden,
            ip_origen=request.client.host if request.client else None,
        )
    except PermisoInsuficienteError as e:
        # 403: el rol no permite la transición. La tarjeta vuelve a su origen.
        return HTMLResponse(
            content=f'<div id="ticket-{ticket_id}" '
                    f'class="rounded-lg border-2 border-red-400 bg-red-50 p-3 text-red-700">'
                    f'<strong>Permiso denegado:</strong> {e.mensaje}</div>',
            status_code=403,
            headers={
                "HX-Trigger": "ticket-error",
                "HX-Reswap": "outerHTML",
            },
        )
    except TransicionInvalidaError as e:
        # 422: transición ilegal. La tarjeta vuelve a su origen.
        return HTMLResponse(
            content=f'<div id="ticket-{ticket_id}" '
                    f'class="rounded-lg border-2 border-amber-400 bg-amber-50 p-3 text-amber-700">'
                    f'<strong>Transición no permitida:</strong> {e.mensaje}</div>',
            status_code=422,
            headers={
                "HX-Trigger": "ticket-error",
                "HX-Reswap": "outerHTML",
            },
        )

    # Éxito: devolver el fragmento HTML de la tarjeta actualizada
    from app.templates.kanban.partials.card import render_tarjeta
    html = render_tarjeta(ticket)
    return HTMLResponse(
        content=html,
        status_code=200,
        headers={
            "HX-Trigger": "ticket-updated",
        },
    )
