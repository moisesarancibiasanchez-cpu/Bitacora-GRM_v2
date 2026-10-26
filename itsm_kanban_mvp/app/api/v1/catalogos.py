"""Endpoints de catálogos: estados, transiciones, SLA, items.

El MVP los expone como JSON read-only (base para futuros mantenedores CRUD).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.estado import Estado
from app.models.transicion import Transicion
from app.models.sla import SLAPolitica
from app.models.catalogo import CatalogoItem
from app.models.usuario import Usuario
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/api/v1/catalogos", tags=["catalogos"])


@router.get("/estados", response_class=JSONResponse)
def listar_estados(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Lista todos los estados activos con sus transiciones permitidas."""
    estados = (
        db.query(Estado)
        .filter(Estado.activo.is_(True))
        .order_by(Estado.orden.asc())
        .all()
    )
    transiciones = db.query(Transicion).filter(Transicion.activo.is_(True)).all()

    # Indexar transiciones por origen
    trans_por_origen: dict[int, list[dict]] = {}
    for t in transiciones:
        trans_por_origen.setdefault(t.origen_id, []).append({
            "id": t.id,
            "destino_id": t.destino_id,
            "destino_nombre": t.estado_destino.nombre,
            "rol_requerido": t.rol_requerido.value,
            "requiere_comentario": t.requiere_comentario,
            "nombre": t.nombre,
        })

    payload = []
    for e in estados:
        payload.append({
            "id": e.id,
            "nombre": e.nombre,
            "descripcion": e.descripcion,
            "orden": e.orden,
            "categoria": e.categoria.value,
            "color": e.color,
            "es_inicial": e.es_inicial,
            "es_final": e.es_final,
            "transiciones_permitidas": trans_por_origen.get(e.id, []),
        })
    return {"estados": payload, "total": len(payload)}


@router.get("/sla", response_class=JSONResponse)
def listar_sla(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    politicas = db.query(SLAPolitica).filter(SLAPolitica.activo.is_(True)).all()
    return {
        "politicas": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "prioridad": p.prioridad.value,
                "minutos_resolucion": p.minutos_resolucion,
                "es_default": p.es_default,
            }
            for p in politicas
        ]
    }


@router.get("/items", response_class=JSONResponse)
def listar_catalogo_items(
    tipo: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Lista los ítems de catálogo (opcionalmente filtrados por tipo)."""
    q = db.query(CatalogoItem).filter(CatalogoItem.activo.is_(True))
    if tipo:
        q = q.filter(CatalogoItem.tipo == tipo.upper())
    items = q.order_by(CatalogoItem.orden.asc(), CatalogoItem.id.asc()).all()
    return {
        "items": [
            {
                "id": i.id,
                "tipo": i.tipo.value,
                "codigo": i.codigo,
                "nombre": i.nombre,
                "descripcion": i.descripcion,
                "color": i.color,
                "orden": i.orden,
            }
            for i in items
        ]
    }
