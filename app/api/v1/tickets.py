"""
Endpoints del módulo de Incidencias.
El más importante: PATCH /tickets/{id}/estado - recibe la señal de HTMX.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError
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

logger = logging.getLogger(__name__)


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
    except SQLAlchemyError as e:
        # 500: error de base de datos no contemplado. Rollback y mensaje claro.
        logger.exception("Error de BD al cambiar estado del ticket %s", ticket_id)
        try:
            db.rollback()
        except Exception:
            pass
        error_msg = str(e.orig) if hasattr(e, 'orig') and e.orig else str(e)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Error al persistir el cambio de estado: {error_msg}",
                "code": "DB_ERROR",
            },
            headers={"HX-Trigger": "ticket-error"},
        )
    except Exception as e:
        # 500: cualquier otro error inesperado. Rollback y mensaje claro.
        logger.exception("Error inesperado al cambiar estado del ticket %s", ticket_id)
        try:
            db.rollback()
        except Exception:
            pass
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Error inesperado al cambiar el estado: {str(e)}",
                "code": "INTERNAL_ERROR",
            },
            headers={"HX-Trigger": "ticket-error"},
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


# ===========================================================================
#  Helper: indica si una transición requiere comentario
#  (el frontend lo consulta antes de hacer drag & drop para mostrar un prompt)
# ===========================================================================
@router.get("/{ticket_id}/transicion-info/{estado_destino_id}")
def transicion_info(
    ticket_id: int,
    estado_destino_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Devuelve metadata de la transición: si requiere comentario, rol permitido, etc."""
    from app.models.estado import Estado, TransicionEstado
    from app.models.ticket import Ticket

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    estado_destino = db.query(Estado).filter(Estado.id == estado_destino_id).first()
    if not estado_destino:
        raise HTTPException(status_code=404, detail="Estado destino no encontrado")

    transicion = (
        db.query(TransicionEstado)
        .filter(
            TransicionEstado.estado_origen_id == ticket.estado_id,
            TransicionEstado.estado_destino_id == estado_destino_id,
        )
        .first()
    )

    if not transicion:
        return {
            "valida": False,
            "motivo": f"No existe una transición válida de '{ticket.estado.nombre}' a '{estado_destino.nombre}'.",
            "requiere_comentario": False,
            "rol_requerido": None,
        }

    return {
        "valida": True,
        "requiere_comentario": transicion.requiere_comentario,
        "rol_requerido": transicion.rol_requerido,
        "descripcion": transicion.descripcion,
    }


# ===========================================================================
#  Helper: vista de detalle de un ticket (HTML, no JSON)
# ===========================================================================
@router.get("/{ticket_id}/detalle-html", response_class=HTMLResponse)
def detalle_html(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Devuelve la vista de detalle completa en HTML (para modal)."""
    from app.models.estado import Estado
    from app.models.ticket import Ticket
    from app.models.comentario import Comentario
    from app.models.adjunto import Adjunto
    from app.models.checklist import Checklist

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        return HTMLResponse("<div>Ticket no encontrado</div>", status_code=404)

    estados = db.query(Estado).order_by(Estado.orden).all()
    comentarios = (
        db.query(Comentario)
        .filter(Comentario.ticket_id == ticket_id)
        .order_by(Comentario.created_at.asc())
        .all()
    )
    adjuntos = (
        db.query(Adjunto)
        .filter(Adjunto.ticket_id == ticket_id)
        .order_by(Adjunto.created_at.desc())
        .all()
    )
    checklists = (
        db.query(Checklist)
        .filter(Checklist.ticket_id == ticket_id)
        .order_by(Checklist.orden.asc())
        .all()
    )

    # Renderizar la plantilla del modal
    from app.templates.tickets.detalle_modal import render_detalle_modal
    html = render_detalle_modal(
        ticket=ticket,
        estados=estados,
        comentarios=comentarios,
        adjuntos=adjuntos,
        checklists=checklists,
        usuario=usuario,
    )
    return HTMLResponse(content=html)
