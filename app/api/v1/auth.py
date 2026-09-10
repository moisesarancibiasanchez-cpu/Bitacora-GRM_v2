"""
Autenticación: login, logout, registro y consulta del usuario actual.

Soporta dos modos:
1) Bearer token (Authorization: Bearer <jwt>) - para integraciones / API.
2) Cookie de sesión 'access_token' - para el frontend web.
3) Fallback X-User-Id (modo demo / pruebas) - controlado en deps.py.

El JWT contiene {"sub": <user_id>, "rol": <rol_value>} y se firma con
SECRET_KEY (configurado en app.core.config).
"""
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app.api.v1.deps import get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario

router = APIRouter(prefix="/auth", tags=["Autenticación"])


# ============== Schemas ==============
class LoginRequest(BaseModel):
    username: str
    password: str


class RegistroRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: str = Field(..., min_length=3, max_length=120)
    nombre_completo: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=6, max_length=128)
    confirm_password: str = Field(..., min_length=6, max_length=128)
    departamento: Optional[str] = Field(None, max_length=120)


class AuthResponse(BaseModel):
    ok: bool
    user_id: Optional[int] = None
    username: Optional[str] = None
    nombre_completo: Optional[str] = None
    rol: Optional[str] = None
    message: Optional[str] = None


def _set_session_cookie(response: Response, user_id: int, rol: str) -> str:
    """Genera JWT, lo pone en cookie y devuelve el token."""
    token = create_access_token({"sub": str(user_id), "rol": rol})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 8,  # 8h
        samesite="lax",
        path="/",
    )
    return token


# ============== Endpoints ==============
@router.post("/login", response_model=AuthResponse)
def login(datos: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Inicia sesión. Acepta username o email en el campo username."""
    ident = datos.username.strip()
    user = (
        db.query(Usuario)
        .filter((Usuario.username == ident) | (Usuario.email == ident))
        .first()
    )
    if not user or not verify_password(datos.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Usuario inactivo. Contacta al administrador.")
    _set_session_cookie(response, user.id, user.rol.value)
    return AuthResponse(
        ok=True, user_id=user.id, username=user.username,
        nombre_completo=user.nombre_completo, rol=user.rol.value,
    )


@router.post("/logout", response_model=AuthResponse)
def logout(response: Response):
    """Cierra la sesión eliminando la cookie."""
    response.delete_cookie("access_token", path="/")
    return AuthResponse(ok=True, message="Sesión cerrada")


@router.post("/registro", response_model=AuthResponse, status_code=201)
def registro(datos: RegistroRequest, response: Response, db: Session = Depends(get_db)):
    """Registra un nuevo usuario con rol solicitante (por defecto)."""
    # Validar coincidencia de contraseñas
    if datos.password != datos.confirm_password:
        raise HTTPException(status_code=400, detail="Las contraseñas no coinciden")

    # Verificar unicidad
    if db.query(Usuario).filter(Usuario.username == datos.username).first():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya está registrado")
    if db.query(Usuario).filter(Usuario.email == datos.email).first():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    # Verificar si es el primer usuario (será admin automáticamente)
    es_primer_usuario = db.query(Usuario).count() == 0
    rol_asignado = RolUsuario.ADMINISTRADOR if es_primer_usuario else RolUsuario.SOLICITANTE

    nuevo = Usuario(
        username=datos.username,
        email=datos.email,
        nombre_completo=datos.nombre_completo,
        hashed_password=hash_password(datos.password),
        departamento=datos.departamento,
        rol=rol_asignado,
        is_active=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    # Auto-login tras registro
    _set_session_cookie(response, nuevo.id, nuevo.rol.value)
    return AuthResponse(
        ok=True, user_id=nuevo.id, username=nuevo.username,
        nombre_completo=nuevo.nombre_completo, rol=nuevo.rol.value,
        message=("Bienvenido. Eres el primer usuario, tienes rol de Administrador."
                 if es_primer_usuario else "Bienvenido a Bitácora GRM."),
    )


@router.get("/me", response_model=AuthResponse)
def me(usuario: Usuario = Depends(get_current_user)):
    """Devuelve info del usuario autenticado actualmente."""
    return AuthResponse(
        ok=True, user_id=usuario.id, username=usuario.username,
        nombre_completo=usuario.nombre_completo, rol=usuario.rol.value,
    )


@router.get("/check")
def check_session(request: Request, usuario: Usuario = Depends(get_current_user)):
    """Endpoint ligero para que el frontend verifique si la sesión es válida."""
    return {
        "authenticated": True,
        "user_id": usuario.id,
        "rol": usuario.rol.value,
        "username": usuario.username,
    }
