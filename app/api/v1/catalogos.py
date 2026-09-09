"""
Endpoints para los mantenedores de catálogos (base para futuros CRUDs).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.catalogo import CatalogoTipo, CatalogoItem
from app.models.etiqueta import Etiqueta
from app.models.usuario import Usuario, RolUsuario


router = APIRouter(prefix="/catalogos", tags=["Catálogos"])


# ---------------- Tipos de catálogo ----------------
@router.get("/tipos")
def listar_tipos(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return db.query(CatalogoTipo).filter(CatalogoTipo.activo == True).all()


@router.post("/tipos", status_code=201)
def crear_tipo(
    nombre: str,
    descripcion: str | None = None,
    esquema: list | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    existe = db.query(CatalogoTipo).filter(CatalogoTipo.nombre == nombre).first()
    if existe:
        raise HTTPException(status_code=400, detail="Ya existe un tipo con ese nombre.")
    tipo = CatalogoTipo(
        nombre=nombre,
        descripcion=descripcion,
        esquema=esquema or [],
    )
    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return tipo


# ---------------- Items de catálogo ----------------
@router.get("/{tipo_id}/items")
def listar_items(
    tipo_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return (
        db.query(CatalogoItem)
        .filter(CatalogoItem.catalogo_tipo_id == tipo_id, CatalogoItem.activo == True)
        .all()
    )


@router.post("/{tipo_id}/items", status_code=201)
def crear_item(
    tipo_id: int,
    nombre: str,
    datos: dict,
    descripcion: str | None = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_role(RolUsuario.AGENTE, RolUsuario.AGENTE_SENIOR, RolUsuario.ADMINISTRADOR)),
):
    tipo = db.query(CatalogoTipo).filter(CatalogoTipo.id == tipo_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de catálogo no existe.")
    item = CatalogoItem(
        catalogo_tipo_id=tipo_id,
        nombre=nombre,
        descripcion=descripcion,
        datos=datos,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ---------------- Usuarios (para filtros y asignaciones) ----------------
@router.get("/usuarios")
def listar_usuarios(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista los usuarios activos. Usado por filtros Kanban y selectores."""
    usuarios = (
        db.query(Usuario)
        .filter(Usuario.is_active == True)  # noqa: E712
        .order_by(Usuario.nombre_completo.asc())
        .all()
    )
    return [
        {
            "id": u.id,
            "nombre_completo": u.nombre_completo,
            "nombre": u.nombre_completo,
            "email": u.email,
            "rol": u.rol.value if u.rol else None,
        }
        for u in usuarios
    ]


# ---------------- Etiquetas (para filtros) ----------------
@router.get("/etiquetas")
def listar_etiquetas(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista las etiquetas activas. Usado por filtros Kanban."""
    etiquetas = (
        db.query(Etiqueta)
        .filter(Etiqueta.activo == True)  # noqa: E712
        .order_by(Etiqueta.nombre.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "nombre": e.nombre,
            "color": e.color or "#64748b",
        }
        for e in etiquetas
    ]
