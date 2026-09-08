"""
API endpoints para las nuevas funcionalidades estilo Trello:
- /etiquetas      CRUD + asignación a tickets
- /tickets/{id}/checklists    CRUD de checklists
- /tickets/{id}/comentarios   CRUD de comentarios con @menciones
- /tickets/{id}/adjuntos      Subida y descarga de archivos
- /buscar                  Búsqueda con filtros avanzados
- /automatizaciones        CRUD de reglas Butler
- /tickets/{id}/detalle    Vista de detalle del ticket
"""
import os
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status, UploadFile, File, Form,
    Query, Request, Response,
)
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_

from app.api.v1.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.ticket import Ticket
from app.models.etiqueta import Etiqueta
from app.models.checklist import Checklist, ChecklistItem
from app.models.comentario import Comentario
from app.models.adjunto import Adjunto
from app.models.automacion import ReglaAutomatizacion
from app.schemas.features import (
    EtiquetaCreate, EtiquetaUpdate, EtiquetaRead,
    ChecklistCreate, ChecklistUpdate, ChecklistRead,
    ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemRead,
    ComentarioCreate, ComentarioRead,
    AdjuntoRead, FiltroTicket,
    ReglaAutomatizacionCreate, ReglaAutomatizacionUpdate, ReglaAutomatizacionRead,
)
from app.services.features_service import (
    EtiquetaService, ChecklistService, ComentarioService, AdjuntoService,
    BusquedaService, MotorAutomatizacion,
)
from app.services.auditoria_service import registrar_auditoria


logger = logging.getLogger(__name__)
router = APIRouter(tags=["features"])


# ==========================================
# ETIQUETAS
# ==========================================
@router.get("/etiquetas", response_model=List[EtiquetaRead])
def listar_etiquetas(
    categoria: Optional[str] = None,
    solo_activas: bool = True,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return EtiquetaService(db).listar(categoria=categoria, solo_activas=solo_activas)


@router.post("/etiquetas", response_model=EtiquetaRead, status_code=201)
def crear_etiqueta(
    datos: EtiquetaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    return EtiquetaService(db).crear(datos.model_dump())


@router.patch("/etiquetas/{etiqueta_id}", response_model=EtiquetaRead)
def actualizar_etiqueta(
    etiqueta_id: int,
    datos: EtiquetaUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    et = EtiquetaService(db).actualizar(etiqueta_id, datos.model_dump(exclude_unset=True))
    if not et:
        raise HTTPException(status_code=404, detail="Etiqueta no encontrada")
    return et


@router.delete("/etiquetas/{etiqueta_id}", status_code=204)
def eliminar_etiqueta(
    etiqueta_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    et = db.query(Etiqueta).filter(Etiqueta.id == etiqueta_id).first()
    if not et:
        raise HTTPException(status_code=404, detail="Etiqueta no encontrada")
    et.activo = False
    db.commit()
    return Response(status_code=204)


@router.post("/tickets/{ticket_id}/etiquetas/{etiqueta_id}", response_model=List[EtiquetaRead])
def asignar_etiqueta(
    ticket_id: int,
    etiqueta_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    EtiquetaService(db).asignar_a_ticket(ticket, etiqueta_id)
    registrar_auditoria(db, ticket.id, user.id, "etiqueta_asignada", valor_nuevo={"etiqueta_id": etiqueta_id})
    # Disparar regla butler
    MotorAutomatizacion(db).disparar("ticket_etiquetado", ticket, {"etiqueta_id": etiqueta_id})
    return ticket.etiquetas


@router.delete("/tickets/{ticket_id}/etiquetas/{etiqueta_id}", response_model=List[EtiquetaRead])
def quitar_etiqueta(
    ticket_id: int,
    etiqueta_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    EtiquetaService(db).quitar_de_ticket(ticket, etiqueta_id)
    registrar_auditoria(db, ticket.id, user.id, "etiqueta_removida", valor_nuevo={"etiqueta_id": etiqueta_id})
    return ticket.etiquetas


# ==========================================
# CHECKLISTS
# ==========================================
@router.get("/tickets/{ticket_id}/checklists", response_model=List[ChecklistRead])
def listar_checklists(
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return ChecklistService(db).listar_de_ticket(ticket_id)


@router.post("/tickets/{ticket_id}/checklists", response_model=ChecklistRead, status_code=201)
def crear_checklist(
    ticket_id: int,
    datos: ChecklistCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    cl = ChecklistService(db).crear(ticket, datos.titulo, [i.model_dump() for i in datos.items])
    registrar_auditoria(db, ticket.id, user.id, "checklist_creada", valor_nuevo={"titulo": datos.titulo})
    db.refresh(cl)
    return cl


@router.delete("/checklists/{checklist_id}", status_code=204)
def eliminar_checklist(
    checklist_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    cl = db.query(Checklist).filter(Checklist.id == checklist_id).first()
    if not cl:
        raise HTTPException(status_code=404, detail="Checklist no encontrada")
    ticket_id = cl.ticket_id
    ChecklistService(db).eliminar(checklist_id)
    registrar_auditoria(db, ticket_id, user.id, "checklist_eliminada", valor_anterior={"checklist_id": checklist_id})
    return Response(status_code=204)


@router.post("/checklists/{checklist_id}/items", response_model=ChecklistItemRead, status_code=201)
def agregar_item(
    checklist_id: int,
    datos: ChecklistItemCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    item = ChecklistService(db).agregar_item(checklist_id, datos.texto, datos.asignado_id)
    if not item:
        raise HTTPException(status_code=404, detail="Checklist no encontrada")
    return item


@router.patch("/checklist-items/{item_id}", response_model=ChecklistItemRead)
def toggle_item(
    item_id: int,
    datos: ChecklistItemUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.post("/checklist-items/{item_id}/toggle", response_model=ChecklistItemRead)
def toggle_item_simple(
    item_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    item = ChecklistService(db).toggle_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return item


@router.delete("/checklist-items/{item_id}", status_code=204)
def eliminar_item(
    item_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    if not ChecklistService(db).eliminar_item(item_id):
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return Response(status_code=204)


# ==========================================
# COMENTARIOS + MENCIONES
# ==========================================
@router.get("/tickets/{ticket_id}/comentarios", response_model=List[ComentarioRead])
def listar_comentarios(
    ticket_id: int,
    incluir_internos: bool = True,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    # Solo agentes ven internos
    if incluir_internos and user.rol == RolUsuario.SOLICITANTE:
        incluir_internos = False
    return ComentarioService(db).listar_de_ticket(ticket_id, incluir_internos)


@router.post("/tickets/{ticket_id}/comentarios", response_model=ComentarioRead, status_code=201)
def crear_comentario(
    ticket_id: int,
    datos: ComentarioCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    com = ComentarioService(db).crear(
        ticket_id=ticket_id,
        usuario_id=user.id,
        texto=datos.texto,
        es_interno=datos.es_interno,
    )
    registrar_auditoria(db, ticket.id, user.id, "comentario_creado", valor_nuevo={"comentario_id": com.id})
    MotorAutomatizacion(db).disparar("ticket_comentado", ticket, {"comentario_id": com.id})
    return com


@router.patch("/comentarios/{comentario_id}", response_model=ComentarioRead)
def editar_comentario(
    comentario_id: int,
    datos: ComentarioCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    com = db.query(Comentario).filter(Comentario.id == comentario_id).first()
    if not com:
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    if com.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
        raise HTTPException(status_code=403, detail="No autorizado para editar")
    com = ComentarioService(db).editar(comentario_id, datos.texto)
    return com


@router.delete("/comentarios/{comentario_id}", status_code=204)
def eliminar_comentario(
    comentario_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    com = db.query(Comentario).filter(Comentario.id == comentario_id).first()
    if not com:
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    if com.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
        raise HTTPException(status_code=403, detail="No autorizado para eliminar")
    ComentarioService(db).eliminar(comentario_id)
    return Response(status_code=204)


# ==========================================
# ADJUNTOS
# ==========================================
@router.get("/tickets/{ticket_id}/adjuntos", response_model=List[AdjuntoRead])
def listar_adjuntos(
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return AdjuntoService(db).listar_de_ticket(ticket_id)


@router.post("/tickets/{ticket_id}/adjuntos", response_model=AdjuntoRead, status_code=201)
async def subir_adjunto(
    ticket_id: int,
    archivo: UploadFile = File(...),
    descripcion: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    contenido = await archivo.read()
    adj, error = AdjuntoService(db).guardar_archivo(
        ticket=ticket,
        usuario=user,
        file_bytes=contenido,
        nombre_original=archivo.filename or "archivo",
        mime_type=archivo.content_type,
        descripcion=descripcion,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    registrar_auditoria(db, ticket.id, user.id, "adjunto_subido", valor_nuevo={
        "adjunto_id": adj.id, "nombre": adj.nombre_original, "tamano": adj.tamano_bytes
    })
    return adj


@router.get("/adjuntos/{adjunto_id}/descargar")
def descargar_adjunto(
    adjunto_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    adj = AdjuntoService(db).obtener(adjunto_id)
    if not adj:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    if not os.path.exists(adj.ruta):
        raise HTTPException(status_code=410, detail="Archivo físico no disponible")
    return FileResponse(
        path=adj.ruta,
        filename=adj.nombre_original,
        media_type=adj.mime_type or "application/octet-stream",
    )


@router.delete("/adjuntos/{adjunto_id}", status_code=204)
def eliminar_adjunto(
    adjunto_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    adj = AdjuntoService(db).obtener(adjunto_id)
    if not adj:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    if adj.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
        raise HTTPException(status_code=403, detail="No autorizado para eliminar")
    AdjuntoService(db).eliminar(adjunto_id)
    return Response(status_code=204)


# ==========================================
# BÚSQUEDA Y FILTROS AVANZADOS
# ==========================================
@router.get("/buscar")
def buscar_tickets(
    texto: Optional[str] = None,
    estados: Optional[str] = Query(None, description="IDs separados por coma"),
    prioridades: Optional[str] = Query(None, description="baja,media,alta,critica"),
    tipos: Optional[str] = Query(None, description="incidencia,solicitud,cambio,problema"),
    etiquetas: Optional[str] = Query(None, description="IDs separados por coma"),
    etiquetas_all: Optional[str] = Query(None, description="AND, IDs separados por coma"),
    asignados: Optional[str] = Query(None, description="IDs separados por coma"),
    creadores: Optional[str] = Query(None, description="IDs separados por coma"),
    catalogos: Optional[str] = Query(None, description="IDs separados por coma"),
    sla_cumplido: Optional[int] = None,
    solo_sin_asignar: Optional[bool] = None,
    solo_con_comentarios: Optional[bool] = None,
    solo_con_adjuntos: Optional[bool] = None,
    ordenar_por: str = "created_at",
    orden: str = "desc",
    limite: int = Query(100, ge=1, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    def parse_list(s):
        if not s:
            return None
        try:
            return [int(x) for x in s.split(",") if x.strip()]
        except ValueError:
            return [x.strip() for x in s.split(",") if x.strip()]

    filtros = {
        "texto": texto,
        "estados": parse_list(estados),
        "prioridades": parse_list(prioridades),
        "tipos": parse_list(tipos),
        "etiquetas": parse_list(etiquetas),
        "etiquetas_all": parse_list(etiquetas_all),
        "asignados": parse_list(asignados),
        "creadores": parse_list(creadores),
        "catalogos": parse_list(catalogos),
        "sla_cumplido": sla_cumplido,
        "solo_sin_asignar": solo_sin_asignar,
        "solo_con_comentarios": solo_con_comentarios,
        "solo_con_adjuntos": solo_con_adjuntos,
        "ordenar_por": ordenar_por,
        "orden": orden,
        "limite": limite,
        "offset": offset,
    }
    tickets, total = BusquedaService(db).buscar(filtros)
    return {
        "total": total,
        "limite": limite,
        "offset": offset,
        "tickets": [
            {
                "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                "prioridad": t.prioridad.value if hasattr(t.prioridad, "value") else t.prioridad,
                "estado_id": t.estado_id,
                "estado_nombre": t.estado.nombre if t.estado else None,
                "asignado_id": t.asignado_id,
                "asignado_nombre": t.asignado.nombre_completo if t.asignado else None,
                "etiquetas": [{"id": e.id, "nombre": e.nombre, "color": e.color} for e in t.etiquetas],
                "total_comentarios": t.total_comentarios,
                "total_adjuntos": t.total_adjuntos,
                "progreso_checklists": t.progreso_checklists,
                "fecha_vencimiento_sla": t.fecha_vencimiento_sla.isoformat() if t.fecha_vencimiento_sla else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tickets
        ],
    }


@router.get("/buscar/estadisticas")
def estadisticas(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return BusquedaService(db).estadisticas()


# ==========================================
# AUTOMATIZACIONES (BUTLER)
# ==========================================
@router.get("/automatizaciones", response_model=List[ReglaAutomatizacionRead])
def listar_reglas(
    disparador: Optional[str] = None,
    solo_activas: bool = True,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    q = db.query(ReglaAutomatizacion)
    if disparador:
        q = q.filter(ReglaAutomatizacion.disparador == disparador)
    if solo_activas:
        q = q.filter(ReglaAutomatizacion.activo == True)  # noqa: E712
    return q.order_by(ReglaAutomatizacion.prioridad).all()


@router.post("/automatizaciones", response_model=ReglaAutomatizacionRead, status_code=201)
def crear_regla(
    datos: ReglaAutomatizacionCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    regla = ReglaAutomatizacion(creador_id=user.id, **datos.model_dump())
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla


@router.patch("/automatizaciones/{regla_id}", response_model=ReglaAutomatizacionRead)
def actualizar_regla(
    regla_id: int,
    datos: ReglaAutomatizacionUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    regla = db.query(ReglaAutomatizacion).filter(ReglaAutomatizacion.id == regla_id).first()
    if not regla:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(regla, k, v)
    db.commit()
    db.refresh(regla)
    return regla


@router.delete("/automatizaciones/{regla_id}", status_code=204)
def eliminar_regla(
    regla_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    regla = db.query(ReglaAutomatizacion).filter(ReglaAutomatizacion.id == regla_id).first()
    if not regla:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    db.delete(regla)
    db.commit()
    return Response(status_code=204)


@router.post("/automatizaciones/{regla_id}/test")
def probar_regla(
    regla_id: int,
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    """Ejecuta una regla manualmente sobre un ticket para probarla."""
    regla = db.query(ReglaAutomatizacion).filter(ReglaAutomatizacion.id == regla_id).first()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not regla or not ticket:
        raise HTTPException(status_code=404, detail="Regla o ticket no encontrado")
    motor = MotorAutomatizacion(db)
    # Replicar la lógica pero solo de esta regla
    from app.services.features_service import EtiquetaService, ComentarioService
    detalles = []
    for cond in (regla.condiciones or []):
        if not motor._evaluar_condicion(ticket, cond):
            return {"exito": False, "detalle": "Condiciones no cumplidas", "detalles": []}
    for acc in (regla.acciones or []):
        detalles.append(motor._ejecutar_accion(ticket, acc))
    db.commit()
    return {"exito": True, "detalles": detalles}


# ==========================================
# DETALLE DE TICKET
# ==========================================
@router.get("/tickets/{ticket_id}/detalle")
def detalle_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Retorna el ticket con todas las relaciones para vista de detalle."""
    ticket = (
        db.query(Ticket)
        .options(
            joinedload(Ticket.estado),
            joinedload(Ticket.creador),
            joinedload(Ticket.asignado),
            joinedload(Ticket.catalogo_tipo),
            joinedload(Ticket.etiquetas),
            joinedload(Ticket.comentarios).joinedload(Comentario.usuario),
            joinedload(Ticket.comentarios).joinedload(Comentario.menciones),
            joinedload(Ticket.checklists).joinedload(Checklist.items),
            joinedload(Ticket.adjuntos),
        )
        .filter(Ticket.id == ticket_id)
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    def usuario_dict(u):
        if not u:
            return None
        return {
            "id": u.id, "username": u.username, "nombre_completo": u.nombre_completo,
            "rol": u.rol.value if hasattr(u.rol, "value") else str(u.rol),
        }

    return {
        "id": ticket.id,
        "codigo": ticket.codigo,
        "titulo": ticket.titulo,
        "descripcion": ticket.descripcion,
        "tipo": ticket.tipo.value if hasattr(ticket.tipo, "value") else str(ticket.tipo),
        "prioridad": ticket.prioridad.value if hasattr(ticket.prioridad, "value") else str(ticket.prioridad),
        "estado_id": ticket.estado_id,
        "estado": {
            "id": ticket.estado.id,
            "nombre": ticket.estado.nombre,
            "color": ticket.estado.color,
        } if ticket.estado else None,
        "creador": usuario_dict(ticket.creador),
        "asignado": usuario_dict(ticket.asignado),
        "catalogo_tipo": {
            "id": ticket.catalogo_tipo.id,
            "nombre": ticket.catalogo_tipo.nombre,
        } if ticket.catalogo_tipo else None,
        "datos_catalogo": ticket.datos_catalogo,
        "fecha_vencimiento_sla": ticket.fecha_vencimiento_sla.isoformat() if ticket.fecha_vencimiento_sla else None,
        "sla_cumplido": ticket.sla_cumplido,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "etiquetas": [
            {"id": e.id, "nombre": e.nombre, "color": e.color, "categoria": e.categoria}
            for e in ticket.etiquetas
        ],
        "checklists": [
            {
                "id": cl.id,
                "titulo": cl.titulo,
                "progreso": cl.progreso(),
                "items": [
                    {
                        "id": it.id, "texto": it.texto, "completado": it.completado,
                        "orden": it.orden, "asignado_id": it.asignado_id,
                    }
                    for it in cl.items
                ],
            }
            for cl in ticket.checklists
        ],
        "comentarios": [
            {
                "id": c.id,
                "texto": c.texto,
                "es_interno": c.es_interno,
                "editado": c.editado,
                "autor": usuario_dict(c.usuario),
                "menciones": [
                    {"id": m.id, "usuario_id": m.usuario_id, "notificado": m.notificado}
                    for m in c.menciones
                ],
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in ticket.comentarios
        ],
        "adjuntos": [
            {
                "id": a.id, "nombre_original": a.nombre_original,
                "tamano_bytes": a.tamano_bytes, "tamano_legible": a.tamano_legible,
                "mime_type": a.mime_type, "es_imagen": a.es_imagen,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "descripcion": a.descripcion,
            }
            for a in ticket.adjuntos
        ],
        "total_comentarios": ticket.total_comentarios,
        "total_adjuntos": ticket.total_adjuntos,
        "total_checklists": ticket.total_checklists,
        "progreso_checklists": ticket.progreso_checklists,
    }
