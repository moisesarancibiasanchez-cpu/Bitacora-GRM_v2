"""
API endpoints para el Reporte Diario de Entregas (admin only).

Endpoints (todos bajo ``/api/v1/admin/reporte-entregas``):

  - GET    /plantilla                       → lee plantilla singleton
  - POST   /plantilla                       → guarda plantilla
  - GET    /destinatarios                   → lista destinatarios
  - POST   /destinatarios                   → crea/upsert destinatario
  - POST   /destinatarios/{id}/toggle       → activa/desactiva
  - POST   /destinatarios/{id}/eliminar     → elimina definitivamente
  - GET    /estados                         → lista estados (para marcar/desmarcar)
  - POST   /estados/{id}/es-entrega         → toggle es_entrega
  - GET    /entregas                        → últimas entregas (default 100)
  - GET    /entregas/resumen                → resumen por día (últimos 7)
  - POST   /regenerar                       → encola generación manual
  - GET    /previsualizar                   → HTML/text sin enviar (para UI)

Todas las rutas validan que el usuario tenga permiso ``admin_reporte_entregas``
(rol administrador). Si no, devuelven 403.

La respuesta de los endpoints HTML devuelve fragments para HTMX.
La respuesta JSON (``.json``) devuelve dicts.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.usuario import Usuario
from app.services.reporte_entregas_service import (
    listar_destinatarios,
    crear_destinatario,
    toggle_destinatario,
    eliminar_destinatario,
    listar_estados_es_entrega,
    marcar_estado_es_entrega,
    listar_ultimas_entregas,
    listar_entregas_por_dia,
    resumen_entregas_por_dia,
    previsualizar_reporte,
    regenerar_reporte,
    obtener_plantilla,
    guardar_plantilla,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/reporte-entregas", tags=["Reporte Entregas (admin)"])


def _require_admin(usuario: Usuario) -> None:
    """Devuelve 403 si el usuario no es administrador."""
    rol = (
        usuario.rol.value
        if hasattr(usuario.rol, "value")
        else str(usuario.rol or "")
    )
    if rol.lower() != "administrador":
        raise HTTPException(
            status_code=403,
            detail="Solo el rol administrador puede gestionar el reporte.",
        )


# ===========================================================================
#  Plantilla
# ===========================================================================
@router.get("/plantilla")
def get_plantilla(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lee la plantilla singleton (JSON)."""
    _require_admin(usuario)
    pl = obtener_plantilla(db)
    return {
        "id": pl.id,
        "habilitado": bool(pl.habilitado),
        "asunto": pl.asunto or "",
        "cuerpo_html": pl.cuerpo_html or "",
        "cuerpo_texto": pl.cuerpo_texto or "",
        "firma": pl.firma or "",
        "created_at": pl.created_at.isoformat() if pl.created_at else None,
        "updated_at": pl.updated_at.isoformat() if pl.updated_at else None,
    }


@router.post("/plantilla")
def post_plantilla(
    habilitado: bool = Form(...),
    asunto: str = Form(...),
    cuerpo_html: str = Form(...),
    cuerpo_texto: str = Form(""),
    firma: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Guarda la plantilla singleton."""
    _require_admin(usuario)
    pl = guardar_plantilla(
        db,
        habilitado=habilitado,
        asunto=asunto,
        cuerpo_html=cuerpo_html,
        cuerpo_texto=cuerpo_texto,
        firma=firma,
        actor_id=usuario.id,
    )
    return JSONResponse(
        {"ok": True, "id": pl.id, "asunto_len": len(pl.asunto or "")},
        headers={
            "HX-Trigger": json.dumps({
                "toast": {
                    "type": "success",
                    "message": "Plantilla del reporte guardada.",
                },
            }),
        },
    )


# ===========================================================================
#  Destinatarios
# ===========================================================================
@router.get("/destinatarios")
def get_destinatarios(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    dests = listar_destinatarios(db)
    return [
        {
            "id": d.id,
            "email": d.email,
            "nombre": d.nombre,
            "rol": d.rol,
            "usuario_id": d.usuario_id,
            "usuario_nombre": (
                d.usuario_obj.nombre_completo if d.usuario_obj else None
            ),
            "activo": bool(d.activo),
            "notas": d.notas,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in dests
    ]


@router.post("/destinatarios")
def post_destinatarios(
    email: str = Form(...),
    nombre: Optional[str] = Form(None),
    rol: Optional[str] = Form(None),
    usuario_id: Optional[int] = Form(None),
    notas: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    try:
        dest, creado = crear_destinatario(
            db,
            email=email,
            nombre=nombre,
            rol=rol,
            usuario_id=usuario_id,
            activo=True,
            notas=notas,
            actor_id=usuario.id,
        )
    except ValueError as e:
        return JSONResponse(
            {"ok": False, "error": str(e)},
            status_code=400,
        )
    return JSONResponse(
        {
            "ok": True,
            "creado": creado,
            "id": dest.id,
            "email": dest.email,
        },
        headers={
            "HX-Trigger": json.dumps({
                "toast": {
                    "type": "success",
                    "message": (
                        "Destinatario creado."
                        if creado else
                        "Destinatario actualizado (ya existía)."
                    ),
                },
                "reporte-destinatario-refresh": {},
            }),
        },
    )


@router.post("/destinatarios/{destinatario_id}/toggle")
def toggle_destinatario_endpoint(
    destinatario_id: int,
    activo: bool = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    try:
        dest = toggle_destinatario(
            db,
            destinatario_id=destinatario_id,
            activo=activo,
            actor_id=usuario.id,
        )
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
    return JSONResponse(
        {"ok": True, "id": dest.id, "activo": bool(dest.activo)},
        headers={
            "HX-Trigger": json.dumps({
                "toast": {
                    "type": "success",
                    "message": (
                        "Destinatario activado."
                        if dest.activo else
                        "Destinatario desactivado."
                    ),
                },
            }),
        },
    )


@router.post("/destinatarios/{destinatario_id}/eliminar")
def eliminar_destinatario_endpoint(
    destinatario_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    try:
        snap = eliminar_destinatario(
            db, destinatario_id=destinatario_id, actor_id=usuario.id,
        )
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
    return JSONResponse(
        {"ok": True, "eliminado": snap},
        headers={
            "HX-Trigger": json.dumps({
                "toast": {
                    "type": "success",
                    "message": f"Destinatario «{snap['email']}» eliminado.",
                },
            }),
        },
    )


# ===========================================================================
#  Estados (marcar/desmarcar es_entrega)
# ===========================================================================
@router.get("/estados")
def get_estados(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    estados = listar_estados_es_entrega(db)
    return [
        {
            "id": e.id,
            "nombre": e.nombre,
            "color": e.color,
            "es_final": bool(e.es_final),
            "es_entrega": bool(getattr(e, "es_entrega", False)),
            "orden": e.orden,
        }
        for e in estados
    ]


@router.post("/estados/{estado_id}/es-entrega")
def toggle_estado_es_entrega(
    estado_id: int,
    es_entrega: bool = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    try:
        estado = marcar_estado_es_entrega(
            db,
            estado_id=estado_id,
            es_entrega=es_entrega,
            actor_id=usuario.id,
        )
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
    return JSONResponse(
        {
            "ok": True,
            "id": estado.id,
            "nombre": estado.nombre,
            "es_entrega": bool(estado.es_entrega),
        },
        headers={
            "HX-Trigger": json.dumps({
                "toast": {
                    "type": "success",
                    "message": (
                        f"Estado «{estado.nombre}»: entregas activadas."
                        if estado.es_entrega else
                        f"Estado «{estado.nombre}»: entregas desactivadas."
                    ),
                },
            }),
        },
    )


# ===========================================================================
#  Entregas / histórico
# ===========================================================================
@router.get("/entregas")
def get_entregas(
    dias: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _require_admin(usuario)
    resumen = resumen_entregas_por_dia(db, dias=dias)
    ultimas = listar_ultimas_entregas(db, limit=200)
    return {
        "resumen": resumen,
        "ultimas": [
            {
                "id": e.id,
                "ticket_codigo": e.ticket_codigo,
                "ticket_titulo": e.ticket_titulo,
                "estado_destino_nombre": e.estado_destino_nombre,
                "asignado_nombre": e.asignado_nombre,
                "fecha_entrega": e.fecha_entrega.isoformat() if e.fecha_entrega else None,
                "reporte_enviado_en": e.reporte_enviado_en.isoformat() if e.reporte_enviado_en else None,
            }
            for e in ultimas
        ],
    }


# ===========================================================================
#  Previsualización y regeneración
# ===========================================================================
@router.get("/previsualizar")
def previsualizar(
    fecha: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Renderiza el reporte SIN enviarlo (para vista previa)."""
    _require_admin(usuario)
    from app.core.config import settings

    try:
        resultado = previsualizar_reporte(
            db, fecha_iso=fecha, base_url=settings.PUBLIC_BASE_URL,
        )
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return resultado


@router.post("/regenerar")
def regenerar(
    fecha: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Encola la tarea Celery para generar y enviar el reporte."""
    _require_admin(usuario)
    try:
        resultado = regenerar_reporte(
            db, fecha_iso=fecha, actor_id=usuario.id,
        )
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return JSONResponse(
        resultado,
        headers={
            "HX-Trigger": json.dumps({
                "toast": {
                    "type": "success" if resultado.get("ok") else "error",
                    "message": (
                        f"Reporte encolado (task_id={resultado.get('task_id')}). "
                        f"Fecha: {resultado.get('fecha')}."
                        if resultado.get("ok") else
                        f"Error encolando: {resultado.get('error')}"
                    ),
                },
            }),
        },
    )


# Import local de json para evitar import circular arriba
import json  # noqa: E402