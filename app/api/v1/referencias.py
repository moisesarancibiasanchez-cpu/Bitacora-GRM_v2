"""
Endpoints API para FEATURE 5: Referencias Internas entre tickets.

Endpoints:
    POST   /api/v1/tickets/{id}/referencias          → agregar referencia
    GET    /api/v1/tickets/{id}/referencias          → listar (bidireccional)
    DELETE /api/v1/referencias/{ref_id}              → eliminar
    GET    /api/v1/tickets/buscar?q=...&excluir=...  → autocompletar selector
    GET    /api/v1/referencias/tipos                 → catálogo de tipos válidos

Todos requieren sesión activa. La creación/eliminación de referencias está
disponible para cualquier usuario autenticado (no se restringe por rol
porque las referencias son anotaciones de baja criticidad, similares a
etiquetas).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_current_user
from app.models.usuario import Usuario
from app.services.referencia_service import (
    ReferenciaError, TicketReferenciaService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/referencias", tags=["referencias-internas"])
# Segundo router para colgar el endpoint de autocompletar bajo ``/tickets``
# (mantiene coherencia con el prefijo REST estándar).
router_tickets = APIRouter(prefix="/tickets", tags=["referencias-internas"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class ReferenciaCreate(BaseModel):
    ticket_referenciado_id: int = Field(..., gt=0)
    tipo: str = Field(
        "relacionado",
        description="Uno de: relacionado, duplicado, padre, hijo, bloquea, bloqueado_por",
    )
    nota: Optional[str] = Field(None, max_length=500)


class ReferenciaRead(BaseModel):
    id: int
    tipo: str
    tipo_nombre: str
    direccion: str  # "saliente" | "entrante"
    ticket_id: int
    ticket_codigo: str
    ticket_titulo: str
    ticket_estado: Optional[str] = None
    nota: Optional[str] = None
    creado_por_id: Optional[int] = None
    created_at: Optional[str] = None


class TicketBusquedaRead(BaseModel):
    id: int
    codigo: str
    titulo: str
    estado_id: Optional[int] = None
    estado_nombre: Optional[str] = None


class TipoReferenciaCatalogo(BaseModel):
    value: str
    nombre: str


# -----------------------------------------------------------------------------
# Endpoints bajo /api/v1/tickets/{id}/referencias
# -----------------------------------------------------------------------------
@router_tickets.post(
    "/{ticket_id}/referencias",
    response_model=ReferenciaRead,
    status_code=201,
)
def agregar_referencia(
    ticket_id: int,
    payload: ReferenciaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea una referencia DESDE ``ticket_id`` HACIA otro ticket."""
    svc = TicketReferenciaService(db)
    try:
        ref = svc.agregar(
            ticket_origen_id=ticket_id,
            ticket_referenciado_id=payload.ticket_referenciado_id,
            tipo=payload.tipo,
            nota=payload.nota,
            creado_por_id=usuario.id,
        )
    except ReferenciaError as e:
        # Duplicados y auto-referencia son 409 (conflicto), no 400.
        if e.codigo in ("duplicado", "auto_referencia"):
            raise HTTPException(
                status_code=409,
                detail={"codigo": e.codigo, "mensaje": e.mensaje},
            )
        raise HTTPException(
            status_code=400,
            detail={"codigo": e.codigo, "mensaje": e.mensaje},
        )

    # Devolvemos en formato "saliente" (porque así lo creamos).
    destino = (
        db.query(__import__("app.models.ticket", fromlist=["Ticket"]).Ticket)
        .filter(__import__("app.models.ticket", fromlist=["Ticket"]).Ticket.id == payload.ticket_referenciado_id)
        .first()
    )
    from app.services.referencia_service import TIPO_REFERENCIA_NOMBRES
    from app.models.ticket_referencia import TipoReferencia

    try:
        tipo_enum = TipoReferencia(payload.tipo)
    except ValueError:
        tipo_enum = ref.tipo

    return ReferenciaRead(
        id=ref.id,
        tipo=tipo_enum.value,
        tipo_nombre=TIPO_REFERENCIA_NOMBRES.get(tipo_enum, tipo_enum.value),
        direccion="saliente",
        ticket_id=payload.ticket_referenciado_id,
        ticket_codigo=destino.codigo if destino else "?",
        ticket_titulo=(destino.titulo if destino else "")[:120],
        ticket_estado=None,
        nota=ref.nota,
        creado_por_id=ref.creado_por_id,
        created_at=ref.created_at.isoformat() if ref.created_at else None,
    )


@router_tickets.get(
    "/{ticket_id}/referencias",
    response_model=List[ReferenciaRead],
)
def listar_referencias_de_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Lista las referencias (salientes + entrantes) de un ticket.

    Una referencia "saliente" es aquella en la que este ticket es el
    origen; una "entrante" es aquella en la que este ticket es el
    destino. La lista se entrega unificada con el campo ``direccion``
    para que la UI pueda etiquetarlas visualmente.
    """
    svc = TicketReferenciaService(db)
    return svc.listar_para_ticket(ticket_id)


@router_tickets.get(
    "/{ticket_id}/referencias/resumen",
)
def resumen_referencias(
    ticket_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Devuelve un resumen compacto para mostrar badges en el header del
    modal: conteo por tipo y por dirección."""
    svc = TicketReferenciaService(db)
    refs = svc.listar_para_ticket(ticket_id)
    resumen = {
        "total": len(refs),
        "salientes": sum(1 for r in refs if r["direccion"] == "saliente"),
        "entrantes": sum(1 for r in refs if r["direccion"] == "entrante"),
        "por_tipo": {},
    }
    for r in refs:
        resumen["por_tipo"][r["tipo"]] = resumen["por_tipo"].get(r["tipo"], 0) + 1
    return resumen


# -----------------------------------------------------------------------------
# Endpoints bajo /api/v1/referencias
# -----------------------------------------------------------------------------
@router.delete("/{ref_id}", status_code=200)
def eliminar_referencia(
    ref_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Elimina una referencia por su ID."""
    svc = TicketReferenciaService(db)
    ok = svc.eliminar(ref_id, usuario_id=usuario.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Referencia no encontrada.")
    return {"ok": True, "id": ref_id}


@router.get("/tipos", response_model=List[TipoReferenciaCatalogo])
def listar_tipos_referencia(
    _: Usuario = Depends(get_current_user),
):
    """Devuelve el catálogo de tipos válidos (para popular un <select>)."""
    return TicketReferenciaService.tipos_validos()


# -----------------------------------------------------------------------------
# Autocompletar (búsqueda de tickets)
# -----------------------------------------------------------------------------
@router_tickets.get("/buscar")
def buscar_tickets_autocompletar(
    request: Request,
    q: str = Query("", description="Texto a buscar (código, título o HU)"),
    excluir: Optional[int] = Query(
        None, description="ID del ticket a excluir de los resultados"
    ),
    limit: int = Query(15, ge=1, le=50),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Busca tickets por código/título/HU para alimentar el selector con
    autocompletar del modal de Referencias.

    Si la petición viene de HTMX (``HX-Request: true``), devuelve un
    fragmento HTML con la lista clickable. Si no, devuelve JSON con la
    lista de ``TicketBusquedaRead``.
    """
    svc = TicketReferenciaService(db)
    resultados = svc.buscar_tickets_para_autocompletar(
        query=q,
        exclude_ticket_id=excluir,
        limit=limit,
    )

    # Detectar si es HTMX → devolver HTML
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return HTMLResponse(_render_search_results_html(resultados, q))

    return [TicketBusquedaRead(**r) for r in resultados]


def _render_search_results_html(resultados: list, query: str = "") -> str:
    """Renderiza la lista de resultados del autocomplete como HTML.

    Cada item usa ``data-ticket-id`` y ``data-codigo-titulo`` para que un
    event listener delegado (instalado por el modal) los traduzca en
    asignación al input hidden y al input visible.

    Esto evita embeber ``{TICKET_ID}`` en el JS (que el endpoint genérico
    no conoce).
    """
    from markupsafe import escape as _esc

    if not resultados:
        return (
            f'<div class="px-3 py-2 text-xs text-slate-500 italic">'
            f'Sin resultados para "{_esc(query)}"</div>'
        )
    items = []
    for r in resultados:
        codigo_titulo = f"{r['codigo']} — {r['titulo']}"
        estado_html = (
            f'<span class="text-[10px] px-1 py-0.5 rounded bg-slate-100 text-slate-600">'
            f'{_esc(r["estado_nombre"])}</span>'
            if r.get("estado_nombre") else ""
        )
        items.append(
            f'<button type="button" '
            f'class="ref-search-option w-full text-left px-3 py-2 hover:bg-indigo-50 '
            f'border-b border-slate-100 last:border-0" '
            f'data-ticket-id="{r["id"]}" '
            f'data-codigo-titulo="{_esc(codigo_titulo)}">'
            f'<div class="flex items-center gap-2">'
            f'<span class="font-mono text-[11px] font-semibold text-indigo-700">'
            f'{_esc(r["codigo"])}</span>'
            f'{estado_html}'
            f'</div>'
            f'<div class="text-[11px] text-slate-600 truncate">{_esc(r["titulo"])}</div>'
            f'</button>'
        )
    return (
        f'<div class="bg-white">'
        + "".join(items)
        + '</div>'
    )
