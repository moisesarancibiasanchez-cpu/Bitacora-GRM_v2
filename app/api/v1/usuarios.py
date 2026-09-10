"""
Gestión de Usuarios (solo Administrador).

Endpoints CRUD para que un Administrador pueda:
- Listar usuarios
- Crear nuevos usuarios (asignando rol)
- Actualizar datos de un usuario (rol, activo, nombre, email, contraseña)
- Desactivar (soft-delete) usuarios
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional, List

from app.api.v1.deps import get_current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])


# ============== Helpers ==============
def _require_admin(usuario: Usuario) -> Usuario:
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Requiere rol Administrador")
    return usuario


# ============== Schemas ==============
class UsuarioCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: str = Field(..., min_length=3, max_length=120)
    nombre_completo: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=6, max_length=128)
    rol: RolUsuario = RolUsuario.SOLICITANTE
    departamento: Optional[str] = Field(None, max_length=120)


class UsuarioUpdate(BaseModel):
    email: Optional[str] = Field(None, min_length=3, max_length=120)
    nombre_completo: Optional[str] = Field(None, min_length=3, max_length=200)
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    rol: Optional[RolUsuario] = None
    departamento: Optional[str] = Field(None, max_length=120)
    is_active: Optional[bool] = None


class UsuarioRead(BaseModel):
    id: int
    username: str
    email: str
    nombre_completo: str
    rol: RolUsuario
    is_active: bool
    departamento: Optional[str] = None
    created_at: Optional[str] = None
    last_login: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_user(cls, user) -> "UsuarioRead":
        """Construye UsuarioRead desde un modelo ORM, serializando datetimes a ISO 8601."""
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            nombre_completo=user.nombre_completo,
            rol=user.rol,
            is_active=user.is_active,
            departamento=user.departamento,
            created_at=user.created_at.isoformat() if getattr(user, 'created_at', None) else None,
            last_login=user.last_login.isoformat() if getattr(user, 'last_login', None) else None,
        )


# ============== Endpoints ==============
@router.get("", response_model=List[UsuarioRead])
def listar_usuarios(
    q: Optional[str] = Query(None, description="Búsqueda en username, email o nombre"),
    rol: Optional[RolUsuario] = None,
    solo_activos: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todos los usuarios. Solo Administrador."""
    _require_admin(usuario)
    query = db.query(Usuario)
    if q:
        patron = f"%{q}%"
        query = query.filter(or_(
            Usuario.username.ilike(patron),
            Usuario.email.ilike(patron),
            Usuario.nombre_completo.ilike(patron),
        ))
    if rol is not None:
        query = query.filter(Usuario.rol == rol)
    if solo_activos:
        query = query.filter(Usuario.is_active == True)  # noqa: E712
    usuarios = query.order_by(Usuario.nombre_completo.asc()).all()
    return [UsuarioRead.from_orm_user(u) for u in usuarios]


@router.get("/{usuario_id}", response_model=UsuarioRead)
def obtener_usuario(usuario_id: int, db: Session = Depends(get_db),
                    usuario: Usuario = Depends(get_current_user)):
    """Obtiene un usuario por ID. Solo Administrador."""
    _require_admin(usuario)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return UsuarioRead.from_orm_user(target)


@router.post("", response_model=UsuarioRead, status_code=201)
def crear_usuario(datos: UsuarioCreate, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(get_current_user)):
    """Crea un usuario nuevo con el rol indicado. Solo Administrador."""
    _require_admin(usuario)
    if db.query(Usuario).filter(Usuario.username == datos.username).first():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    if db.query(Usuario).filter(Usuario.email == datos.email).first():
        raise HTTPException(status_code=400, detail="El email ya está registrado")
    nuevo = Usuario(
        username=datos.username,
        email=datos.email,
        nombre_completo=datos.nombre_completo,
        hashed_password=hash_password(datos.password),
        rol=datos.rol,
        departamento=datos.departamento,
        is_active=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return UsuarioRead.from_orm_user(nuevo)


@router.patch("/{usuario_id}", response_model=UsuarioRead)
def actualizar_usuario(usuario_id: int, datos: UsuarioUpdate,
                       db: Session = Depends(get_db),
                       usuario: Usuario = Depends(get_current_user)):
    """Actualiza datos de un usuario. Solo Administrador."""
    _require_admin(usuario)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Evitar que el admin se desactive a sí mismo
    if target.id == usuario.id and datos.is_active is False:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo")

    cambios = datos.model_dump(exclude_unset=True)
    if "password" in cambios and cambios["password"]:
        cambios["hashed_password"] = hash_password(cambios.pop("password"))

    # Validar unicidad si se cambia email
    if "email" in cambios and cambios["email"] != target.email:
        if db.query(Usuario).filter(
            Usuario.email == cambios["email"],
            Usuario.id != usuario_id,
        ).first():
            raise HTTPException(status_code=400, detail="El email ya está en uso por otro usuario")

    for k, v in cambios.items():
        setattr(target, k, v)
    db.commit()
    db.refresh(target)
    return UsuarioRead.from_orm_user(target)


@router.delete("/{usuario_id}", status_code=204)
def desactivar_usuario(usuario_id: int, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(get_current_user)):
    """Desactiva (soft-delete) un usuario. Solo Administrador."""
    _require_admin(usuario)
    if usuario_id == usuario.id:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    target.is_active = False
    db.commit()
    return None


@router.post("/{usuario_id}/reactivar", response_model=UsuarioRead)
def reactivar_usuario(usuario_id: int, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(get_current_user)):
    """Reactiva un usuario previamente desactivado. Solo Administrador."""
    _require_admin(usuario)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    target.is_active = True
    db.commit()
    db.refresh(target)
    return UsuarioRead.from_orm_user(target)
