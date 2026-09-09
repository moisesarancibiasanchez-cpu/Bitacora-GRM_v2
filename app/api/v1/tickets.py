"""
Endpoints del módulo de Incidencias.
El más importante: PATCH /tickets/{id}/estado - recibe la señal de HTMX.
"""
import csv
import io
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import or_, and_, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket
from app.models.usuario import Usuario
from app.models.etiqueta import Etiqueta, ticket_etiquetas
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


# ===========================================================================
#  Búsqueda y filtrado (Sprint 1 - Feature Trello)
# ===========================================================================
@router.get("/buscar/query")
def buscar_tickets(
    q: str | None = Query(None, description="Texto libre: busca en titulo, codigo, descripcion"),
    etiqueta_id: int | None = Query(None, description="ID de etiqueta"),
    asignado_id: int | None = Query(None, description="ID de usuario asignado"),
    prioridad: str | None = Query(None, description="critica|alta|media|baja"),
    estado_id: int | None = Query(None),
    archivado: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Búsqueda y filtrado de tickets estilo Trello.

    - ``q``: texto libre que busca en codigo, titulo, descripcion.
    - ``etiqueta_id``: filtra por etiqueta exacta.
    - ``asignado_id``: filtra por usuario asignado.
    - ``prioridad``: filtra por prioridad.
    - ``estado_id``: filtra por estado.
    - ``archivado``: por defecto False (no mostrar archivados).
    """
    query = db.query(Ticket)
    if q:
        patron = f"%{q}%"
        query = query.filter(
            or_(
                Ticket.codigo.ilike(patron),
                Ticket.titulo.ilike(patron),
                Ticket.descripcion.ilike(patron),
            )
        )
    if etiqueta_id is not None:
        query = query.join(ticket_etiquetas, ticket_etiquetas.c.ticket_id == Ticket.id).filter(
            ticket_etiquetas.c.etiqueta_id == etiqueta_id
        )
    if asignado_id is not None:
        query = query.filter(Ticket.asignado_id == asignado_id)
    if prioridad:
        query = query.filter(Ticket.prioridad == prioridad)
    if estado_id is not None:
        query = query.filter(Ticket.estado_id == estado_id)
    if archivado is not None:
        query = query.filter(Ticket.archivado == archivado)
    else:
        query = query.filter(Ticket.archivado == False)  # noqa: E712
    tickets = query.order_by(Ticket.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": t.id,
            "codigo": t.codigo,
            "titulo": t.titulo,
            "estado_id": t.estado_id,
            "estado_nombre": t.estado.nombre if t.estado else None,
            "estado_color": t.estado.color if t.estado else "#94a3b8",
            "prioridad": t.prioridad.value if t.prioridad else "media",
            "asignado_id": t.asignado_id,
            "asignado_nombre": t.asignado.nombre_completo if t.asignado else None,
            "etiquetas": [{"id": e.id, "nombre": e.nombre, "color": e.color} for e in t.etiquetas],
            "archivado": t.archivado,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in tickets
    ]


# ===========================================================================
#  Duplicar tarjeta (Sprint 1 - Feature Trello básica)
# ===========================================================================
@router.post("/{ticket_id}/duplicar", response_model=TicketRead, status_code=201)
def duplicar_ticket(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea una copia exacta de un ticket con sufijo '(Copia)'.

    - Conserva: titulo + ' (Copia)', descripcion, tipo, prioridad, asignado, etiquetas, catalogos.
    - Resetea: estado (vuelve al estado inicial), orden (ultimo + 1), SLA (recalculado),
      archivado (False), creador (usuario actual).
    - Auditoria: registra 'ticket_duplicado' con referencia al origen.
    """
    from app.models.estado import Estado
    from app.models.auditoria import Auditoria
    from app.models.ticket import TipoIncidencia, Prioridad
    from datetime import timedelta
    from sqlalchemy import func as sqlfunc

    original = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    # Estado inicial: primer estado con es_inicial=True, sino el primero por orden
    estado_inicial = (
        db.query(Estado).filter(Estado.es_inicial == True).first()  # noqa: E712
        or db.query(Estado).order_by(Estado.orden).first()
    )

    # Generar nuevo codigo correlativo
    ultimo = db.query(sqlfunc.max(Ticket.id)).scalar() or 0
    codigo = f"GRM-INC-2026-{(ultimo + 1):06d}"

    # Calcular nueva fecha de SLA
    fecha_sla = None
    if estado_inicial and estado_inicial.sla_horas:
        fecha_sla = datetime.utcnow() + timedelta(hours=estado_inicial.sla_horas)

    copia = Ticket(
        codigo=codigo,
        titulo=f"{original.titulo} (Copia)",
        descripcion=original.descripcion,
        tipo=original.tipo,
        prioridad=original.prioridad,
        estado_id=estado_inicial.id if estado_inicial else original.estado_id,
        creador_id=usuario.id,
        asignado_id=original.asignado_id,
        catalogo_tipo_id=original.catalogo_tipo_id,
        datos_catalogo=original.datos_catalogo,
        fecha_vencimiento_sla=fecha_sla,
        sla_cumplido=-1,
        archivado=False,
        tablero_id=original.tablero_id,
    )
    db.add(copia)
    db.flush()

    # Copiar etiquetas many-to-many
    for et in original.etiquetas:
        copia.etiquetas.append(et)

    # Auditoria: registrar la duplicacion
    aud = Auditoria(
        ticket_id=copia.id,
        usuario_id=usuario.id,
        accion="ticket_duplicado",
        valor_anterior={"ticket_origen_id": original.id, "codigo_origen": original.codigo},
        valor_nuevo={"ticket_copia_id": copia.id, "codigo_copia": copia.codigo},
        ip_origen=request.client.host if request.client else None,
    )
    db.add(aud)
    db.commit()
    db.refresh(copia)
    return copia


# ===========================================================================
#  Exportar tickets a CSV (Sprint 1 - Feature Trello)
# ===========================================================================
@router.get("/exportar/csv")
def exportar_csv(
    estado_id: int | None = Query(None),
    etiqueta_id: int | None = Query(None),
    asignado_id: int | None = Query(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Exporta los tickets filtrados a un CSV descargable."""
    query = db.query(Ticket).filter(Ticket.archivado == False)  # noqa: E712
    if estado_id is not None:
        query = query.filter(Ticket.estado_id == estado_id)
    if etiqueta_id is not None:
        query = query.join(ticket_etiquetas, ticket_etiquetas.c.ticket_id == Ticket.id).filter(
            ticket_etiquetas.c.etiqueta_id == etiqueta_id
        )
    if asignado_id is not None:
        query = query.filter(Ticket.asignado_id == asignado_id)
    tickets = query.order_by(Ticket.created_at.desc()).limit(1000).all()

    # Construir CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Codigo", "Titulo", "Tipo", "Prioridad", "Estado",
        "Asignado", "Creador", "Etiquetas", "SLA_Vencimiento", "SLA_Cumplido",
        "Creado", "Actualizado",
    ])
    for t in tickets:
        writer.writerow([
            t.id,
            t.codigo,
            t.titulo,
            t.tipo.value if t.tipo else "",
            t.prioridad.value if t.prioridad else "",
            t.estado.nombre if t.estado else "",
            t.asignado.nombre_completo if t.asignado else "",
            t.creador.nombre_completo if t.creador else "",
            ";".join(e.nombre for e in t.etiquetas),
            t.fecha_vencimiento_sla.isoformat() if t.fecha_vencimiento_sla else "",
            "Si" if t.sla_cumplido == 1 else ("No" if t.sla_cumplido == 0 else "Pendiente"),
            t.created_at.isoformat() if t.created_at else "",
            t.updated_at.isoformat() if t.updated_at else "",
        ])

    output.seek(0)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="tickets_bitacora_{timestamp}.csv"',
        },
    )
