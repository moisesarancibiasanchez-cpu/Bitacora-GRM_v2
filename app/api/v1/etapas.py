"""
Endpoints API para FEATURE 4: Etapas de proyecto UAT (sub-bars en Gantt).

Endpoints:
    GET    /api/v1/etapas                  → listar catálogo
    POST   /api/v1/etapas                  → crear nueva etapa (admin)
    PATCH  /api/v1/etapas/{id}             → editar etapa (admin)
    GET    /api/v1/etapas/ticket/{tid}     → listar etapas de un ticket
    POST   /api/v1/etapas/ticket/{tid}/auto-asignar   → forzar asignación de 10 etapas
    PATCH  /api/v1/etapas/ticket/{tid}/{etapa_id}     → editar fechas/notas

Todos requieren sesión activa. La edición del catálogo requiere rol
``administrador``. La actualización de fechas/notas de un ticket la
puede hacer cualquier usuario con permiso de edición sobre el ticket
(mismo criterio que ``PATCH /tickets/{id}``).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_current_user
from app.models.etapa_proyecto import EtapaProyecto, TicketEtapa
from app.models.usuario import Usuario, RolUsuario
from app.services.etapa_service import EtapaError, EtapaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/etapas", tags=["etapas"])


# -----------------------------------------------------------------------------
# Schemas Pydantic
# -----------------------------------------------------------------------------
class EtapaOut(BaseModel):
    """Representación de una etapa del catálogo."""
    id: int
    codigo: str
    nombre: str
    orden: int
    color: str
    activo: bool

    class Config:
        from_attributes = True


class TicketEtapaOut(BaseModel):
    """Representación de una asignación ticket-etapa (lo que consume el Gantt)."""
    id: int
    ticket_id: int
    etapa_id: int
    etapa_codigo: str
    etapa_nombre: str
    etapa_color: str
    etapa_orden: int
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    completado: bool
    orden: int
    notas: Optional[str] = None


class EtapaCreate(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=40)
    nombre: str = Field(..., min_length=1, max_length=120)
    orden: int = Field(..., ge=1, le=999)
    color: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")


class EtapaUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=120)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    orden: Optional[int] = Field(default=None, ge=1, le=999)
    activo: Optional[bool] = None


class TicketEtapaUpdate(BaseModel):
    fecha_inicio: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_fin: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    completado: Optional[bool] = None
    notas: Optional[str] = Field(default=None, max_length=4000)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _ticket_etapa_to_dict(te: TicketEtapa) -> dict:
    """Serializa una ``TicketEtapa`` a un dict apto para ``jsonable_encoder``."""
    return {
        "id": te.id,
        "ticket_id": te.ticket_id,
        "etapa_id": te.etapa_id,
        "etapa_codigo": te.etapa.codigo if te.etapa else "",
        "etapa_nombre": te.etapa.nombre if te.etapa else "",
        "etapa_color": te.etapa.color if te.etapa else "#6366f1",
        "etapa_orden": te.etapa.orden if te.etapa else 0,
        "fecha_inicio": te.fecha_inicio,
        "fecha_fin": te.fecha_fin,
        "completado": bool(te.completado),
        "orden": te.orden,
        "notas": te.notas,
    }


def _require_admin(usuario: Usuario) -> None:
    if not usuario or usuario.rol.value != "administrador":
        raise HTTPException(
            status_code=403,
            detail="Solo administradores pueden modificar el catálogo de etapas.",
        )


# -----------------------------------------------------------------------------
# Catálogo
# -----------------------------------------------------------------------------
@router.get("", response_model=list[EtapaOut])
def listar_etapas(
    solo_activas: bool = True,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista el catálogo de etapas del proyecto."""
    svc = EtapaService(db)
    etapas = svc.listar_etapas(solo_activas=solo_activas)
    return [
        EtapaOut(
            id=e.id,
            codigo=e.codigo,
            nombre=e.nombre,
            orden=e.orden,
            color=e.color,
            activo=bool(e.activo),
        )
        for e in etapas
    ]


@router.post("", response_model=EtapaOut, status_code=201)
def crear_etapa(
    payload: EtapaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea una etapa nueva en el catálogo. Solo admin."""
    _require_admin(usuario)
    # Validar código duplicado
    existente = (
        db.query(EtapaProyecto)
        .filter(EtapaProyecto.codigo == payload.codigo)
        .first()
    )
    if existente:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una etapa con código '{payload.codigo}'.",
        )
    e = EtapaProyecto(
        codigo=payload.codigo,
        nombre=payload.nombre,
        orden=payload.orden,
        color=payload.color,
        activo=1,
    )
    db.add(e)
    try:
        db.commit()
    except Exception as ex:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"No se pudo crear la etapa: {ex}"
        )
    db.refresh(e)
    return EtapaOut(
        id=e.id, codigo=e.codigo, nombre=e.nombre,
        orden=e.orden, color=e.color, activo=bool(e.activo),
    )


@router.patch("/{etapa_id}", response_model=EtapaOut)
def actualizar_etapa(
    etapa_id: int,
    payload: EtapaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Edita una etapa existente. Solo admin."""
    _require_admin(usuario)
    e = db.query(EtapaProyecto).filter(EtapaProyecto.id == etapa_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    if payload.nombre is not None:
        e.nombre = payload.nombre
    if payload.color is not None:
        e.color = payload.color
    if payload.orden is not None:
        e.orden = payload.orden
    if payload.activo is not None:
        e.activo = 1 if payload.activo else 0
    try:
        db.commit()
    except Exception as ex:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"No se pudo actualizar: {ex}"
        )
    db.refresh(e)
    return EtapaOut(
        id=e.id, codigo=e.codigo, nombre=e.nombre,
        orden=e.orden, color=e.color, activo=bool(e.activo),
    )


# -----------------------------------------------------------------------------
# Asignaciones por ticket
# -----------------------------------------------------------------------------
@router.get("/ticket/{ticket_id}", response_model=list[TicketEtapaOut])
def listar_etapas_de_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Devuelve las 10 etapas del ticket con sus fechas planificadas."""
    svc = EtapaService(db)
    rows = svc.listar_etapas_de_ticket(ticket_id)
    return [_ticket_etapa_to_dict(te) for te in rows]


@router.post("/ticket/{ticket_id}/auto-asignar", response_model=list[TicketEtapaOut])
def auto_asignar_etapas(
    ticket_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Fuerza la asignación de las 10 etapas a un ticket. Idempotente."""
    from app.models.ticket import Ticket
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    svc = EtapaService(db)
    svc.asignar_etapas_iniciales(ticket)
    db.commit()
    rows = svc.listar_etapas_de_ticket(ticket_id)
    return [_ticket_etapa_to_dict(te) for te in rows]


@router.patch("/ticket/{ticket_id}/{etapa_id}", response_model=TicketEtapaOut)
def actualizar_etapa_ticket(
    ticket_id: int,
    etapa_id: int,
    payload: TicketEtapaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Edita las fechas / notas / marcado de una etapa concreta del ticket."""
    svc = EtapaService(db)
    try:
        te = svc.actualizar_etapa_ticket(
            ticket_id=ticket_id,
            etapa_id=etapa_id,
            fecha_inicio=payload.fecha_inicio,
            fecha_fin=payload.fecha_fin,
            completado=payload.completado,
            notas=payload.notas,
        )
    except EtapaError as ex:
        code = 404 if ex.codigo == "asignacion_no_encontrada" else 400
        raise HTTPException(status_code=code, detail=ex.mensaje) from ex
    # Garantizar que la relación ``etapa`` esté cargada para serializar.
    db.refresh(te)
    return _ticket_etapa_to_dict(te)
