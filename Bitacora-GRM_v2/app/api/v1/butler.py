"""
Endpoints para automatizaciones Butler (Reglas, Botones, Comandos programados).

Sprint 1 - Feature Trello premium: completar el CRUD de reglas Butler.
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.automacion import ReglaAutomatizacion
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/butler", tags=["Butler"])


# ==========================================
# REGLAS DE AUTOMATIZACION
# ==========================================
class ReglaAccion(BaseModel):
    tipo: str = Field(..., description="set_estado | add_etiqueta | remove_etiqueta | set_asignado | add_comentario | notify | archive")
    parametros: dict = Field(default_factory=dict)


class ReglaCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    disparador: str = Field(..., description="ticket_creado | ticket_etiquetado | ticket_asignado | ticket_estado_cambiado | cada_dia | cada_semana")
    # 'condiciones' se almacena en una columna JSON, puede ser dict o list.
    condiciones: Optional[object] = Field(default_factory=dict)
    acciones: List[dict] = Field(..., description="Lista de acciones a ejecutar")
    activo: bool = True


class ReglaUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    disparador: Optional[str] = None
    condiciones: Optional[object] = None
    acciones: Optional[List[dict]] = None
    activo: Optional[bool] = None


class ReglaRead(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None
    disparador: str
    # La columna condiciones es JSON; aceptar cualquier estructura.
    condiciones: Optional[object] = None
    acciones: list
    activo: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/reglas", response_model=List[ReglaRead])
def listar_reglas(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todas las reglas de automatización."""
    return db.query(ReglaAutomatizacion).order_by(ReglaAutomatizacion.nombre).all()


@router.post("/reglas", response_model=ReglaRead, status_code=201)
def crear_regla(
    datos: ReglaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea una nueva regla de automatización.

    Disparadores soportados:
    - ticket_creado
    - ticket_etiquetado
    - ticket_asignado
    - ticket_estado_cambiado
    - cada_dia (cron: 0 9 * * *)
    - cada_semana (cron: 0 9 * * 1)
    """
    # Validar disparador
    disparadores_validos = {
        "ticket_creado", "ticket_etiquetado", "ticket_asignado",
        "ticket_estado_cambiado", "cada_dia", "cada_semana",
    }
    if datos.disparador not in disparadores_validos:
        raise HTTPException(
            status_code=400,
            detail=f"Disparador inválido. Opciones: {sorted(disparadores_validos)}",
        )
    # Validar acciones
    if not datos.acciones or len(datos.acciones) == 0:
        raise HTTPException(status_code=400, detail="Debe especificar al menos una acción")
    acciones_validas = {
        "set_estado", "add_etiqueta", "remove_etiqueta",
        "set_asignado", "add_comentario", "notify", "archive",
    }
    for a in datos.acciones:
        if a.get("tipo") not in acciones_validas:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de acción inválido: {a.get('tipo')}. Opciones: {sorted(acciones_validas)}",
            )

    regla = ReglaAutomatizacion(
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        disparador=datos.disparador,
        condiciones=datos.condiciones or {},
        acciones=datos.acciones,
        activo=datos.activo,
        creador_id=usuario.id,
    )
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla


@router.patch("/reglas/{regla_id}", response_model=ReglaRead)
def actualizar_regla(
    regla_id: int,
    datos: ReglaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Actualiza una regla existente (parcial)."""
    regla = db.query(ReglaAutomatizacion).filter(ReglaAutomatizacion.id == regla_id).first()
    if not regla:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    cambios = datos.model_dump(exclude_unset=True)
    for k, v in cambios.items():
        setattr(regla, k, v)
    db.commit()
    db.refresh(regla)
    return regla


@router.delete("/reglas/{regla_id}", status_code=204)
def eliminar_regla(
    regla_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Elimina una regla de automatización."""
    regla = db.query(ReglaAutomatizacion).filter(ReglaAutomatizacion.id == regla_id).first()
    if not regla:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    db.delete(regla)
    db.commit()
    return None
