"""
Endpoints para gestionar el catálogo de estados y sus transiciones.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.estado import Estado, TransicionEstado
from app.models.usuario import Usuario, RolUsuario
from app.schemas.ticket import EstadoRead, TransicionEstadoRead


router = APIRouter(prefix="/estados", tags=["Estados"])


@router.get("", response_model=list[EstadoRead])
def listar_estados(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todos los estados del flujo, ordenados para el Kanban."""
    return db.query(Estado).order_by(Estado.orden.asc()).all()


@router.get("/transiciones", response_model=list[TransicionEstadoRead])
def listar_transiciones(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todas las transiciones válidas del flujo (lectura de la matriz)."""
    return db.query(TransicionEstado).all()


@router.post("", response_model=EstadoRead, status_code=201)
def crear_estado(
    payload: EstadoRead,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Crea un nuevo estado (solo administradores)."""
    existe = db.query(Estado).filter(Estado.nombre == payload.nombre).first()
    if existe:
        raise HTTPException(status_code=400, detail="Ya existe un estado con ese nombre.")
    estado = Estado(**payload.model_dump())
    db.add(estado)
    db.commit()
    db.refresh(estado)
    return estado


@router.post("/transiciones", status_code=201)
def crear_transicion(
    estado_origen_id: int,
    estado_destino_id: int,
    rol_requerido: str = "agente",
    requiere_comentario: bool = False,
    descripcion: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Crea una transición válida del flujo ITSM."""
    trans = TransicionEstado(
        estado_origen_id=estado_origen_id,
        estado_destino_id=estado_destino_id,
        rol_requerido=rol_requerido,
        requiere_comentario=requiere_comentario,
        descripcion=descripcion,
    )
    db.add(trans)
    db.commit()
    db.refresh(trans)
    return trans
