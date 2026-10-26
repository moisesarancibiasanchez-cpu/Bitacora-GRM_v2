"""Endpoints del tablero Kanban: vista HTML + endpoint HTMX para mover tickets."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.usuario import Usuario
from app.api.v1.deps import get_current_user
from app.services.kanban_service import (
    obtener_columnas_kanban,
    mover_ticket,
    TransicionInvalidaError,
    PermisoInsuficienteError,
)

router = APIRouter(tags=["kanban"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/kanban", response_class=HTMLResponse)
def tablero_kanban(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Renderiza el tablero Kanban completo."""
    columnas = obtener_columnas_kanban(db)
    return templates.TemplateResponse(
        "kanban/tablero.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "usuario": usuario,
            "columnas": columnas,
        },
    )


@router.post("/api/v1/kanban/tickets/{ticket_id}/mover", response_class=HTMLResponse)
def api_mover_ticket(
    ticket_id: int,
    request: Request,
    estado_id: int = Form(...),
    posicion: int = Form(0),
    comentario: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Endpoint HTMX: mueve un ticket a otro estado.

    - Valida la transición según las reglas ITSM (Transicion).
    - Valida el rol del usuario.
    - Si todo OK: inserta auditoría obligatoria + dispara Celery.
    - Retorna el fragmento HTML del ticket para que HTMX refresque la columna.
    - Si falla: retorna 422 con HX-Reswap='none' para que la tarjeta vuelva a su origen.
    """
    try:
        ticket_data = mover_ticket(
            db=db,
            ticket_id=ticket_id,
            estado_destino_id=estado_id,
            usuario=usuario,
            nueva_posicion=posicion,
            comentario=comentario,
        )
    except (TransicionInvalidaError, PermisoInsuficienteError) as exc:
        # Forzar a que la tarjeta vuelva a su columna original (sin swap en cliente).
        return HTMLResponse(
            content=f'<div id="kanban-error" class="text-xs text-rose-600">{exc.detail}</div>',
            status_code=exc.status_code,
            headers={"HX-Reswap": "none", "HX-Trigger": "kanban-error"},
        )
    except HTTPException as exc:
        return HTMLResponse(
            content=f'<div id="kanban-error" class="text-xs text-rose-600">{exc.detail}</div>',
            status_code=exc.status_code,
            headers={"HX-Reswap": "none", "HX-Trigger": "kanban-error"},
        )

    # Render del fragmento de tarjeta (lo que HTMX inyectará).
    return templates.TemplateResponse(
        "kanban/_tarjeta.html",
        {"request": request, "t": ticket_data, "usuario": usuario},
    )


@router.get("/api/v1/kanban/columnas", response_class=JSONResponse)
def api_columnas(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Endpoint JSON con todas las columnas (útil para refresh completo)."""
    return {"columnas": obtener_columnas_kanban(db)}
