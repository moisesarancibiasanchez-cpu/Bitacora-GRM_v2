"""Endpoints de gestión de tickets (CRUD básico para el MVP)."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.ticket import Ticket, PrioridadTicket
from app.models.estado import Estado
from app.models.auditoria import AuditoriaEvento, TipoEvento
from app.models.usuario import Usuario
from app.api.v1.deps import get_current_user

router = APIRouter(tags=["tickets"])
templates = Jinja2Templates(directory="app/templates")


def _generar_codigo_ticket(db: Session) -> str:
    """Genera un código tipo TKT-0001, TKT-0002, ..."""
    ultimo = db.query(Ticket).order_by(Ticket.id.desc()).first()
    siguiente = (ultimo.id + 1) if ultimo else 1
    return f"TKT-{siguiente:05d}"


@router.post("/tickets/nuevo")
def crear_ticket(
    request: Request,
    titulo: str = Form(...),
    descripcion: str = Form(""),
    prioridad: str = Form("MEDIA"),
    estado_id: int = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea un nuevo ticket en el estado inicial (o el estado elegido)."""
    # Validar prioridad
    try:
        prio_enum = PrioridadTicket(prioridad.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Prioridad inválida: {prioridad}")

    estado = db.get(Estado, estado_id)
    if not estado or not estado.activo:
        raise HTTPException(status_code=422, detail="Estado inválido")

    # Posición: al final de la columna
    max_pos = (
        db.query(Ticket)
        .filter(Ticket.estado_id == estado_id)
        .order_by(Ticket.posicion.desc())
        .first()
    )
    nueva_pos = (max_pos.posicion + 1) if max_pos else 0

    ticket = Ticket(
        codigo=_generar_codigo_ticket(db),
        titulo=titulo.strip()[:255],
        descripcion=descripcion,
        estado_id=estado_id,
        prioridad=prio_enum,
        creador_id=usuario.id,
        posicion=nueva_pos,
    )
    db.add(ticket)
    db.flush()  # para tener ticket.id

    db.add(
        AuditoriaEvento(
            ticket_id=ticket.id,
            tipo=TipoEvento.CREADO,
            actor_id=usuario.id,
            actor_username=usuario.username,
            valor_anterior="",
            valor_nuevo=f"Ticket creado en estado «{estado.nombre}»",
            comentario=titulo[:120],
        )
    )
    db.commit()
    db.refresh(ticket)

    # Redirect al kanban para refrescar
    return RedirectResponse(url="/kanban", status_code=303)


@router.get("/tickets/{ticket_id}/auditoria", response_class=HTMLResponse)
def ver_auditoria(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Fragmento HTMX con la tabla de auditoría del ticket."""
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no existe")
    eventos = (
        db.query(AuditoriaEvento)
        .filter(AuditoriaEvento.ticket_id == ticket_id)
        .order_by(AuditoriaEvento.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "kanban/_auditoria.html",
        {"request": request, "ticket": ticket, "eventos": eventos, "usuario": usuario},
    )
