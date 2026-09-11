"""
Autenticación: login, logout, registro y consulta del usuario actual.

Soporta dos modos:
1) Bearer token (Authorization: Bearer <jwt>) - para integraciones / API.
2) Cookie de sesión 'access_token' - para el frontend web.
3) Fallback X-User-Id (modo demo / pruebas) - controlado en deps.py.

El JWT contiene {"sub": <user_id>, "rol": <rol_value>} y se firma con
SECRET_KEY (configurado en app.core.config).
"""
import json as _json
import re
from fastapi import APIRouter, Depends, HTTPException, Response, Request, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app.api.v1.deps import get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.db.session import get_db
from app.models.auditoria import Auditoria
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


class CambiarPasswordRequest(BaseModel):
    """Payload para cambio de contraseña por el propio usuario."""
    password_actual: str = Field(..., min_length=6, max_length=128)
    password_nuevo: str = Field(..., min_length=6, max_length=128)
    password_nuevo_confirm: str = Field(..., min_length=6, max_length=128)


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


# ============== Endpoints para formularios HTML ==============
# Los endpoints anteriores (JSON) se mantienen para integraciones / API.
# Los siguientes aceptan application/x-www-form-urlencoded (lo que envían
# los formularios HTML nativos / HTMX) y devuelven HX-Redirect en éxito
# o un fragmento HTML con el error para mostrarlo en la página.

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]{3,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _error_html(msg: str) -> HTMLResponse:
    """Fragmento HTML para mostrar mensajes de error en el formulario."""
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
        status_code=400,
    )


@router.post("/login-form")
def login_form(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Login para formularios HTML (HTMX / form-urlencoded).

    En éxito: responde con cabecera HX-Redirect hacia /kanban y setea
    la cookie de sesión. En fallo: devuelve un fragmento HTML con
    el motivo del error para mostrarlo en #login-msg.
    """
    ident = (username or "").strip()
    pwd = password or ""
    if not ident or not pwd:
        return _error_html("Usuario y contraseña son obligatorios.")

    user = (
        db.query(Usuario)
        .filter((Usuario.username == ident) | (Usuario.email == ident))
        .first()
    )
    if not user or not verify_password(pwd, user.hashed_password):
        return _error_html("Credenciales inválidas.")
    if not user.is_active:
        return HTMLResponse(
            content=(
                '<div role="alert" class="text-xs text-yellow-800 bg-yellow-50 '
                'border border-yellow-200 rounded p-2 mb-2">'
                'Usuario inactivo. Contacta al administrador.</div>'
            ),
            status_code=403,
        )

    token = create_access_token({"sub": str(user.id), "rol": user.rol.value})
    resp = Response(content="", status_code=200)
    resp.headers["HX-Redirect"] = "/kanban"
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 8,  # 8h
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/registro-form", status_code=200)
def registro_form(
    nombre_completo: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    departamento: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Registro para formularios HTML (HTMX / form-urlencoded).

    En éxito: auto-login y HX-Redirect a /kanban.
    En fallo: fragmento HTML con el motivo del error.
    """
    nombre = (nombre_completo or "").strip()
    user = (username or "").strip()
    mail = (email or "").strip()
    pwd = password or ""
    pwd2 = confirm_password or ""
    depto = (departamento or "").strip() or None

    # Validaciones
    if len(nombre) < 3 or len(nombre) > 200:
        return _error_html("El nombre completo debe tener entre 3 y 200 caracteres.")
    if not _USERNAME_RE.match(user):
        return _error_html(
            "El usuario debe tener entre 3 y 64 caracteres y solo puede "
            "contener letras, números, guion y guion bajo."
        )
    if not _EMAIL_RE.match(mail) or len(mail) > 120:
        return _error_html("El email no es válido.")
    if len(pwd) < 6 or len(pwd) > 128:
        return _error_html("La contraseña debe tener entre 6 y 128 caracteres.")
    if pwd != pwd2:
        return _error_html("Las contraseñas no coinciden.")

    # Unicidad
    if db.query(Usuario).filter(Usuario.username == user).first():
        return _error_html("El nombre de usuario ya está registrado.")
    if db.query(Usuario).filter(Usuario.email == mail).first():
        return _error_html("El email ya está registrado.")

    # Primer usuario -> Administrador
    es_primer_usuario = db.query(Usuario).count() == 0
    rol_asignado = (
        RolUsuario.ADMINISTRADOR if es_primer_usuario else RolUsuario.SOLICITANTE
    )

    nuevo = Usuario(
        username=user,
        email=mail,
        nombre_completo=nombre,
        hashed_password=hash_password(pwd),
        departamento=depto,
        rol=rol_asignado,
        is_active=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    # Auto-login
    token = create_access_token({"sub": str(nuevo.id), "rol": nuevo.rol.value})
    resp = Response(content="", status_code=200)
    resp.headers["HX-Redirect"] = "/kanban"
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 8,
        samesite="lax",
        path="/",
    )
    return resp


# ============== Cambio de contraseña (auto-servicio) ==============
def _client_ip(request: Request) -> Optional[str]:
    """Obtiene la IP del cliente respetando cabeceras de proxy."""
    if not request:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64] or None
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()[:64] or None
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


def _registrar_cambio_password_auditoria(
    db: Session, usuario_id: int, ip: Optional[str]
) -> None:
    """Inserta un registro de auditoría. Errores se ignoran para no bloquear el cambio."""
    try:
        db.add(
            Auditoria(
                ticket_id=None,
                usuario_id=usuario_id,
                accion="CAMBIO_PASSWORD",
                valor_anterior=None,
                valor_nuevo={"origen": "auto_servicio"},
                comentario="El usuario cambió su propia contraseña.",
                ip_origen=ip,
            )
        )
    except Exception:
        # Si el modelo no está disponible o la tabla falla, no interrumpimos
        # el flujo principal (el cambio de contraseña ya es seguro).
        pass


@router.post("/cambiar-password", response_model=AuthResponse)
def cambiar_password(
    datos: CambiarPasswordRequest,
    response: Response,
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cambia la contraseña del usuario autenticado (modo JSON / API).

    - Requiere la contraseña actual.
    - Rechaza si la nueva coincide con la actual.
    - Persiste el hash y re-emite el JWT (la cookie de sesión se renueva).
    - Registra la acción en la tabla de auditoría.
    """
    if datos.password_nuevo != datos.password_nuevo_confirm:
        raise HTTPException(
            status_code=400,
            detail="La nueva contraseña y su confirmación no coinciden.",
        )

    target = db.query(Usuario).filter(Usuario.id == usuario.id).first()
    if not target or not target.is_active:
        raise HTTPException(status_code=403, detail="Usuario no disponible.")

    if not verify_password(datos.password_actual, target.hashed_password):
        raise HTTPException(
            status_code=401, detail="La contraseña actual es incorrecta."
        )

    if verify_password(datos.password_nuevo, target.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="La nueva contraseña debe ser diferente a la actual.",
        )

    target.hashed_password = hash_password(datos.password_nuevo)
    _registrar_cambio_password_auditoria(db, target.id, _client_ip(request))

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="No se pudo actualizar la contraseña. Intenta de nuevo.",
        )

    # Re-emitir cookie para mantener la sesión activa con el mismo usuario/rol
    _set_session_cookie(response, target.id, target.rol.value)

    return AuthResponse(
        ok=True,
        user_id=target.id,
        username=target.username,
        nombre_completo=target.nombre_completo,
        rol=target.rol.value,
        message="Contraseña actualizada correctamente.",
    )


@router.post("/cambiar-password-form", status_code=200)
def cambiar_password_form(
    request: Request,
    password_actual: str = Form(...),
    password_nuevo: str = Form(...),
    password_nuevo_confirm: str = Form(...),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Variante form-urlencoded para HTMX.

    En éxito: emite cabecera `HX-Trigger: cambio-password-ok` con un payload JSON
    que el frontend usa para cerrar el modal y mostrar un toast.
    En fallo: devuelve un fragmento HTML con el mensaje de error.
    """
    pwd_actual = password_actual or ""
    pwd_nuevo = password_nuevo or ""
    pwd_confirm = password_nuevo_confirm or ""

    if len(pwd_actual) < 6 or len(pwd_actual) > 128:
        return _error_html("La contraseña actual debe tener entre 6 y 128 caracteres.")
    if len(pwd_nuevo) < 6 or len(pwd_nuevo) > 128:
        return _error_html("La nueva contraseña debe tener entre 6 y 128 caracteres.")
    if pwd_nuevo != pwd_confirm:
        return _error_html("La nueva contraseña y su confirmación no coinciden.")

    target = db.query(Usuario).filter(Usuario.id == usuario.id).first()
    if not target or not target.is_active:
        return HTMLResponse(
            content=(
                '<div role="alert" class="text-xs text-yellow-800 bg-yellow-50 '
                'border border-yellow-200 rounded p-2 mb-2">'
                'Tu usuario no está disponible. Contacta al administrador.</div>'
            ),
            status_code=403,
        )

    if not verify_password(pwd_actual, target.hashed_password):
        return _error_html("La contraseña actual es incorrecta.")

    if verify_password(pwd_nuevo, target.hashed_password):
        return _error_html("La nueva contraseña debe ser diferente a la actual.")

    target.hashed_password = hash_password(pwd_nuevo)
    _registrar_cambio_password_auditoria(db, target.id, _client_ip(request))

    try:
        db.commit()
    except Exception:
        db.rollback()
        return _error_html(
            "No se pudo actualizar la contraseña. Intenta de nuevo."
        )

    # Re-emitir cookie y notificar al frontend
    payload = _json.dumps(
        {"message": "Contraseña actualizada correctamente."}
    )
    resp = Response(content="", status_code=200)
    resp.headers["HX-Trigger"] = "cambio-password-ok"
    resp.headers["HX-Trigger-Evento"] = "cambio-password-ok"
    # Algunos clientes HTMX leen el JSON desde el header
    resp.headers["HX-Trigger-Detalle"] = payload
    _set_session_cookie(resp, target.id, target.rol.value)
    return resp
