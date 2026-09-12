"""
Endpoints para servir el tablero Kanban (HTML renderizado en servidor).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket
from app.models.usuario import Usuario
from app.services.ticket_service import TicketService


router = APIRouter(prefix="/kanban", tags=["Kanban"])


def get_templates() -> Jinja2Templates:
    """Reutiliza la instancia global de Jinja2Templates de ``app.main``
    para garantizar que los filtros personalizados (p.ej. ``truncate_text``)
    estén registrados. Crear una instancia nueva cada request rompe
    los filtros y produce ``TemplateAssertionError``."""
    from app.main import templates
    return templates


@router.get("", response_class=HTMLResponse)
def tablero_kanban(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Renderiza el tablero Kanban completo."""
    templates = get_templates()
    service = TicketService(db)
    estados = service.listar_kanban()

    # Pre-cargar tickets por estado
    tickets_por_estado: dict[int, list[Ticket]] = {}
    for estado in estados:
        tickets_por_estado[estado.id] = (
            db.query(Ticket)
            .filter(Ticket.estado_id == estado.id)
            .order_by(Ticket.created_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        "kanban/index.html",
        {
            "request": request,
            "usuario": usuario,
            "estados": estados,
            "tickets_por_estado": tickets_por_estado,
        },
    )


@router.get("/columna/{estado_id}", response_class=HTMLResponse)
def columna_kanban(
    estado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Devuelve el fragmento HTML de una columna (para refresco HTMX)."""
    from app.models.estado import Estado
    from app.templates.kanban.partials.column import render_columna
    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        return HTMLResponse("<div>Estado no encontrado</div>", status_code=404)
    tickets = (
        db.query(Ticket)
        .filter(Ticket.estado_id == estado_id)
        .order_by(Ticket.created_at.desc())
        .all()
    )
    return HTMLResponse(render_columna(estado, tickets))
