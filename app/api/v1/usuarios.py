"""
Gestión de Usuarios (solo Administrador).

Endpoints CRUD para que un Administrador pueda:
- Listar usuarios
- Crear nuevos usuarios (asignando rol)
- Actualizar datos de un usuario (rol, activo, nombre, email, contraseña)
- Desactivar (soft-delete) usuarios

Hay dos variantes de POST/PATCH:
  - /api/v1/usuarios             (JSON, Pydantic) - para integraciones / API
  - /api/v1/usuarios/crear-form  (form-data)       - para el formulario HTML / HTMX
  - /api/v1/usuarios/{id}/editar-form (form-data)  - para el formulario HTML / HTMX
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Query, Form, Request
from fastapi.responses import HTMLResponse, Response
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


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]{3,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _error_fragment(msg: str, status: int = 400) -> HTMLResponse:
    """Fragmento HTML para mostrar errores dentro de #form-msg (HTMX swap)."""
    safe = (
        msg.replace("&", "&amp;")
           .replace("<", "&lt;")
           .replace(">", "&gt;")
    )
    return HTMLResponse(
        content=(
            f'<div role="alert" class="text-xs text-red-700 bg-red-50 '
            f'border border-red-200 rounded p-2 mb-2">{safe}</div>'
        ),
        status_code=status,
    )


def _ok_empty(hx_trigger: Optional[str] = None) -> Response:
    """Respuesta vacía con HX-Trigger opcional. El frontend cierra el modal
    al ver `event.detail.successful` en `hx-on::after-request`."""
    resp = Response(content="", status_code=200)
    if hx_trigger:
        resp.headers["HX-Trigger"] = hx_trigger
    return resp


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


# ============== Endpoints FORM-DATA (para el modal HTMX) ==============
# El frontend (templates/usuarios/form.html) envía application/x-www-form-urlencoded.
# Devuelven un fragmento HTML de error en #form-msg o 200 OK (vacío) en éxito.
# El cliente cierra el modal y recarga la tabla en `hx-on::after-request`.

@router.post("/crear-form", response_class=HTMLResponse)
def crear_usuario_form(
    username: str = Form(...),
    email: str = Form(...),
    nombre_completo: str = Form(...),
    password: str = Form(...),
    rol: str = Form("solicitante"),
    departamento: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea un usuario nuevo desde el formulario HTML. Solo Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return _error_fragment("Requiere rol Administrador.", 403)

    user = (username or "").strip()
    mail = (email or "").strip()
    nombre = (nombre_completo or "").strip()
    pwd = password or ""
    depto = (departamento or "").strip() or None

    # Validaciones (mismas reglas que el registro público)
    if not _USERNAME_RE.match(user):
        return _error_fragment(
            "El usuario debe tener entre 3 y 64 caracteres y solo puede "
            "contener letras, números, guion y guion bajo."
        )
    if not _EMAIL_RE.match(mail) or len(mail) > 120:
        return _error_fragment("El email no es válido.")
    if len(nombre) < 3 or len(nombre) > 200:
        return _error_fragment("El nombre completo debe tener entre 3 y 200 caracteres.")
    if len(pwd) < 6 or len(pwd) > 128:
        return _error_fragment("La contraseña debe tener entre 6 y 128 caracteres.")
    try:
        rol_enum = RolUsuario(rol)
    except ValueError:
        return _error_fragment(f"Rol inválido: {rol}")

    # Unicidad
    if db.query(Usuario).filter(Usuario.username == user).first():
        return _error_fragment("El nombre de usuario ya está registrado.")
    if db.query(Usuario).filter(Usuario.email == mail).first():
        return _error_fragment("El email ya está registrado.")

    nuevo = Usuario(
        username=user,
        email=mail,
        nombre_completo=nombre,
        hashed_password=hash_password(pwd),
        departamento=depto,
        rol=rol_enum,
        is_active=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return _ok_empty(hx_trigger='{"usuario-created": {"id": ' + str(nuevo.id) + '}}')


@router.post("/{usuario_id}/editar-form", response_class=HTMLResponse)
def editar_usuario_form(
    usuario_id: int,
    nombre_completo: str = Form(...),
    email: str = Form(...),
    rol: str = Form(...),
    departamento: str = Form(""),
    password: str = Form(""),
    is_active: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Edita un usuario existente desde el formulario HTML. Solo Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return _error_fragment("Requiere rol Administrador.", 403)

    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        return _error_fragment("Usuario no encontrado.", 404)

    nombre = (nombre_completo or "").strip()
    mail = (email or "").strip()
    depto = (departamento or "").strip() or None
    pwd = password or ""

    if len(nombre) < 3 or len(nombre) > 200:
        return _error_fragment("El nombre completo debe tener entre 3 y 200 caracteres.")
    if not _EMAIL_RE.match(mail) or len(mail) > 120:
        return _error_fragment("El email no es válido.")
    try:
        rol_enum = RolUsuario(rol)
    except ValueError:
        return _error_fragment(f"Rol inválido: {rol}")

    # Cambiar email: validar unicidad
    if mail != target.email:
        if db.query(Usuario).filter(
            Usuario.email == mail, Usuario.id != usuario_id
        ).first():
            return _error_fragment("El email ya está en uso por otro usuario.")

    # Cambiar contraseña solo si se envió
    if pwd:
        if len(pwd) < 6 or len(pwd) > 128:
            return _error_fragment("La contraseña debe tener entre 6 y 128 caracteres.")
        target.hashed_password = hash_password(pwd)

    # Evitar que el admin se desactive a sí mismo
    activo_bool = is_active in ("true", "on", "1", "yes")
    if target.id == usuario.id and not activo_bool:
        return _error_fragment("No puedes desactivarte a ti mismo.")

    target.nombre_completo = nombre
    target.email = mail
    target.departamento = depto
    target.rol = rol_enum
    target.is_active = activo_bool
    db.commit()
    db.refresh(target)
    return _ok_empty(hx_trigger='{"usuario-updated": {"id": ' + str(target.id) + '}}')


@router.post("/{usuario_id}/desactivar-form", response_class=HTMLResponse)
def desactivar_usuario_form(
    usuario_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Soft-delete (is_active=False) desde la tabla. Solo Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return _error_fragment("Requiere rol Administrador.", 403)
    if usuario_id == usuario.id:
        return _error_fragment("No puedes eliminarte a ti mismo.")
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        return _error_fragment("Usuario no encontrado.", 404)
    target.is_active = False
    db.commit()
    return _ok_empty()


@router.post("/{usuario_id}/reactivar-form", response_class=HTMLResponse)
def reactivar_usuario_form(
    usuario_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Reactiva un usuario. Solo Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return _error_fragment("Requiere rol Administrador.", 403)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        return _error_fragment("Usuario no encontrado.", 404)
    target.is_active = True
    db.commit()
    return _ok_empty()
