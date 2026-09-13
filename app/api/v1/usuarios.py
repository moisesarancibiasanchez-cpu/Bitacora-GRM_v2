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
import json as _json
import re
import secrets
import string
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Form, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional, List

logger = logging.getLogger(__name__)

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.models.auditoria import Auditoria
from app.models.usuario import Usuario, RolUsuario
from app.services.credenciales_service import (
    CredencialesResult,
    enviar_credenciales_iniciales,
    generar_password_provisoria,
)

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


@router.get("/smtp-status")
def smtp_status(usuario: Usuario = Depends(get_current_user)):
    """
    Devuelve el estado actual de la configuración de envío de emails.
    Solo Administrador (datos operativos).

    Expone los 3 transportes disponibles (en orden de preferencia):
      1) Resend HTTP API  (HTTPS puerto 443, recomendado en PaaS).
      2) SMTP clásico     (puertos 25/465/587, a veces bloqueado).
      3) log local        (modo desarrollo, fallback final).

    NOTA: esta ruta DEBE declararse ANTES de ``/{usuario_id}`` para que
    FastAPI la prefiera sobre el path-paramétrico (de lo contrario
    ``/smtp-status`` se parsea como ``usuario_id`` y devuelve 422).
    """
    _require_admin(usuario)
    # Importación local para no acoplar el router al servicio de email.
    from app.services.email_service import get_transport_info
    info = get_transport_info()
    info["public_base_url"] = settings.PUBLIC_BASE_URL
    return info


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


# ============== Endpoints de envío de credenciales ==============
class EnviarCredencialesResponse(BaseModel):
    """Respuesta del endpoint de envío de credenciales."""
    ok: bool
    sent: bool
    transport: str  # "smtp" | "log" | "disabled"
    to: str
    subject: str
    detail: Optional[str] = None
    message: str
    password_generada: Optional[str] = None  # solo en dev/demo


@router.post(
    "/{usuario_id}/enviar-credenciales",
    response_model=EnviarCredencialesResponse,
)
def enviar_credenciales(
    usuario_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Envía (o re-envía) las credenciales iniciales a un usuario.

    1. Genera una nueva contraseña provisoria.
    2. La hashea y la persiste en la BD (resetea la anterior).
    3. Envía el email con la contraseña al usuario.
    4. Audita la acción.

    Solo Administrador. La contraseña se devuelve en la respuesta SOLO
    en modo desarrollo (cuando el envío real es a un archivo de log).
    En producción (SMTP real) la contraseña NO se devuelve por seguridad.
    """
    _require_admin(usuario)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not target.is_active:
        raise HTTPException(
            status_code=400,
            detail="El usuario está desactivado. Reactívelo antes de enviar credenciales.",
        )
    if not target.email:
        raise HTTPException(
            status_code=400,
            detail="El usuario no tiene email registrado.",
        )

    try:
        result: CredencialesResult = enviar_credenciales_iniciales(
            db,
            target=target,
            actor=usuario,
        )
    except Exception as exc:
        # Cualquier excepción no controlada en el flujo de envío se
        # traduce a una respuesta JSON limpia (en vez del 500 HTML por
        # defecto de FastAPI), para que el frontend pueda parsear y
        # mostrar el error al usuario.
        logger.exception("[enviar_credenciales] Fallo inesperado: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        # Devolvemos ok=False con la misma forma que EnviarCredencialesResponse
        # para que el modal del frontend pueda mostrar el detalle.
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "sent": False,
                "transport": "error",
                "to": target.email,
                "subject": "",
                "detail": f"{type(exc).__name__}: {exc}",
                "message": (
                    "Ocurrió un error al enviar las credenciales. "
                    "Revisa el log del servidor para más detalle."
                ),
                "password_generada": None,
            },
        )

    # En modo dev/log, devolvemos la contraseña generada para que el
    # admin la pueda ver (en SMTP/API real NUNCA se devuelve).
    pwd_visible = result.password_generada if result.transport == "log" else None

    if result.transport == "disabled":
        msg = "No se pudo enviar el correo: el usuario no tiene email."
    elif result.transport == "log":
        # Distinguir: ¿el log es por SMTP bloqueado o por falta de config?
        # result.detail trae "smtp_falló: ..." cuando el SMTP SÍ estaba
        # configurado pero el envío falló (timeout, DNS, etc.).
        detail = (result.detail or "").lower()
        smtp_intent_failed = (
            "smtp" in detail
            or "timeout" in detail
            or "refused" in detail
            or "connection" in detail
            or "resend" in detail
        )
        if smtp_intent_failed:
            msg = (
                "SMTP/API configurados pero el envío falló (lo más probable: "
                "puertos 25/465/587 bloqueados por el proveedor PaaS). "
                "El correo quedó respaldado en tmp/app.email.log. "
                "Configura RESEND_API_KEY en Railway para envío por HTTPS."
            )
        else:
            msg = (
                "Modo desarrollo: el correo se persistió en tmp/app.email.log "
                "porque no hay transporte configurado. "
                "La contraseña generada se muestra a continuación."
            )
    else:
        msg = f"Credenciales enviadas correctamente a {result.to}."

    return EnviarCredencialesResponse(
        ok=True,
        sent=result.sent,
        transport=result.transport,
        to=result.to,
        subject=result.subject,
        detail=result.detail,
        message=msg,
        password_generada=pwd_visible,
    )


class PreviewEmailResponse(BaseModel):
    """Vista previa del email que se enviaría."""
    to: str
    subject: str
    body_text: str
    body_html: str
    smtp_configured: bool
    password_preview: str


@router.get(
    "/{usuario_id}/preview-email",
    response_model=PreviewEmailResponse,
)
def preview_email_credenciales(
    usuario_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Devuelve una vista previa del email de credenciales que se enviaría
    al usuario, con una contraseña simulada. NO envía nada.

    Sirve para que el admin revise el contenido del correo antes de
    confirmar el envío. Solo Administrador.
    """
    _require_admin(usuario)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not target.email:
        raise HTTPException(
            status_code=400,
            detail="El usuario no tiene email registrado.",
        )

    # Contraseña simulada (NO se persiste)
    pwd_preview = generar_password_provisoria()
    rol_str = (
        target.rol.value if hasattr(target.rol, "value") else str(target.rol)
    )
    from app.services.email_service import email_credenciales_iniciales, get_transport_info
    subject, body, html = email_credenciales_iniciales(
        nombre_completo=target.nombre_completo or target.username,
        email_destino=target.email,
        username=target.username,
        password=pwd_preview,
        rol=rol_str,
        departamento=target.departamento,
        url_sistema=settings.PUBLIC_BASE_URL or "http://localhost:8000",
    )

    # Estado real del transporte: considera Resend API → SMTP → log.
    # Si solo SMTP está "configurado" pero los puertos están bloqueados
    # por el proveedor PaaS, igualmente lo marcamos como "configurado"
    # en el preview (el modal se encarga de avisar al admin).
    transport_info = get_transport_info()
    active_transport = transport_info["active_transport"]
    smtp_ok = active_transport in ("resend-api", "smtp")

    return PreviewEmailResponse(
        to=target.email,
        subject=subject,
        body_text=body,
        body_html=html,
        smtp_configured=smtp_ok,
        password_preview=pwd_preview,
    )


@router.get(
    "/{usuario_id}/preview-email-html",
    response_class=HTMLResponse,
)
def preview_email_credenciales_html(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Devuelve el MODAL HTML de previsualización/envío de credenciales.
    Es el que usa el botón "📧" de la tabla de usuarios.
    """
    _require_admin(usuario)
    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        return _error_fragment("Usuario no encontrado.", 404)
    if not target.is_active:
        return _error_fragment(
            "El usuario está desactivado. Reactívelo antes de enviar credenciales.",
            400,
        )
    if not target.email:
        return _error_fragment("El usuario no tiene email registrado.", 400)

    # Contraseña simulada (NO se persiste)
    pwd_preview = generar_password_provisoria()
    rol_str = (
        target.rol.value if hasattr(target.rol, "value") else str(target.rol)
    )
    from app.services.email_service import email_credenciales_iniciales, get_transport_info
    subject, body_text, body_html = email_credenciales_iniciales(
        nombre_completo=target.nombre_completo or target.username,
        email_destino=target.email,
        username=target.username,
        password=pwd_preview,
        rol=rol_str,
        departamento=target.departamento,
        url_sistema=settings.PUBLIC_BASE_URL or "http://localhost:8000",
    )

    # Estado real del transporte (Resend API → SMTP → log). El modal
    # usa active_transport para mostrar el banner correcto según el caso.
    transport_info = get_transport_info()
    active_transport = transport_info["active_transport"]
    smtp_ok = active_transport in ("resend-api", "smtp")

    # Render template: reusar la instancia global de main.py para heredar
    # los filtros Jinja2 personalizados (truncate_text, etc.).
    # Import local para evitar import circular.
    from app.main import templates as app_templates
    return app_templates.TemplateResponse(
        "usuarios/credenciales_modal.html",
        {
            "request": request,
            "target": target,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "smtp_configured": smtp_ok,
            "active_transport": active_transport,
            "transport_info": transport_info,
            "password_preview": pwd_preview,
        },
    )


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
    enviar_credenciales: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea un usuario nuevo desde el formulario HTML. Solo Administrador.

    Si ``enviar_credenciales`` viene marcado (true/on/1/yes), se envía
    automáticamente un email con las credenciales al usuario recién
    creado. La contraseña NO se regenera: se usa la misma que se acaba
    de crear.
    """
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return _error_fragment("Requiere rol Administrador.", 403)

    user = (username or "").strip()
    mail = (email or "").strip()
    nombre = (nombre_completo or "").strip()
    pwd = password or ""
    depto = (departamento or "").strip() or None
    enviar = enviar_credenciales in ("true", "on", "1", "yes")

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

    # Auto-envío de credenciales si se marcó el checkbox
    if enviar and nuevo.email:
        try:
            enviar_credenciales_iniciales(
                db,
                target=nuevo,
                actor=usuario,
                password_plana=pwd,        # reusar la misma pwd creada
                persistir_password=False,   # ya está persistida
            )
        except Exception as exc:  # pragma: no cover
            # El usuario ya fue creado; no rompemos la operación.
            import logging
            logging.getLogger(__name__).warning(
                "[credenciales] Auto-envío falló: %s", exc
            )

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


# ============== Reset de contraseña por Administrador ==============
@router.get("/{usuario_id}/reset-password-modal", response_class=HTMLResponse)
def reset_password_modal(
    usuario_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Devuelve el fragmento HTML del modal de reset de contraseña (admin).

    Se carga por HTMX desde el botón "Cambiar contraseña" en la tabla de
    usuarios. El administrador NO necesita conocer la contraseña actual
    del objetivo: define una nueva y la confirma.
    """
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return HTMLResponse(
            content=(
                '<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">'
                '<div class="bg-white rounded-xl p-6 max-w-md shadow-2xl">'
                '<p class="text-sm text-red-700">Requiere rol Administrador.</p>'
                '</div></div>'
            ),
            status_code=403,
        )

    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        return HTMLResponse(
            content=(
                '<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">'
                '<div class="bg-white rounded-xl p-6 max-w-md shadow-2xl">'
                '<p class="text-sm text-red-700">Usuario no encontrado.</p>'
                '</div></div>'
            ),
            status_code=404,
        )

    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [
        os.path.join(base_dir, "templates", "usuarios", "admin_reset_password_modal.html"),
        os.path.join(base_dir, "app", "templates", "usuarios", "admin_reset_password_modal.html"),
    ]
    template_path = next((p for p in candidates if os.path.exists(p)), None)
    if not template_path:
        return HTMLResponse(
            content=(
                '<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">'
                '<div class="bg-white rounded-xl p-6 max-w-md shadow-2xl">'
                '<p class="text-sm text-red-700">No se encontró la plantilla del modal.</p>'
                '</div></div>'
            ),
            status_code=500,
        )
    with open(template_path, "r", encoding="utf-8") as fh:
        html = fh.read()

    # Renderizado mínimo: solo {{ usuario.id }}, {{ usuario.username }} y
    # {{ usuario.nombre_completo }} se usan en el partial. Jinja2 no es
    # estrictamente necesario aquí; hacemos un replace controlado.
    safe_username = (
        target.username
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_nombre = (
        target.nombre_completo
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    html = (
        html
        .replace("{{ usuario.id }}", str(target.id))
        .replace("{{ usuario.username }}", safe_username)
        .replace("{{ usuario.nombre_completo }}", safe_nombre)
    )
    return HTMLResponse(content=html, status_code=200)


@router.post("/{usuario_id}/reset-password-form", response_class=HTMLResponse)
def reset_password_form(
    usuario_id: int,
    request: Request,
    password_nuevo: str = Form(...),
    password_nuevo_confirm: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Cambia la contraseña de otro usuario (solo Administrador).

    No requiere la contraseña actual. Emite los eventos HTMX:
      - `cambio-password-admin-ok`     en éxito
      - `cambio-password-admin-error`  en fallo

    Además pinta un fragmento HTML de error en el target del formulario
    (`#admin-reset-pwd-msg`) para feedback inmediato.
    """
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return _error_fragment("Requiere rol Administrador.", 403)

    target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not target:
        return _error_fragment("Usuario no encontrado.", 404)

    pwd = (password_nuevo or "").strip()
    confirm = (password_nuevo_confirm or "").strip()

    if len(pwd) < 6 or len(pwd) > 128:
        return _error_fragment("La nueva contraseña debe tener entre 6 y 128 caracteres.")
    if pwd != confirm:
        return _error_fragment("La nueva contraseña y su confirmación no coinciden.")

    # No permitir que el admin use la misma clave que ya tiene el objetivo
    # (evita "no-op" silencioso).
    try:
        from app.core.security import verify_password
        if verify_password(pwd, target.hashed_password):
            return _error_fragment("La nueva contraseña debe ser diferente a la actual.")
    except Exception:
        pass

    target.hashed_password = hash_password(pwd)

    # Auditoría: registrar el reset (origen = admin). Errores se ignoran
    # para no bloquear el cambio, igual que en el flujo de auto-servicio.
    try:
        ip = None
        try:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                ip = fwd.split(",")[0].strip()[:64] or None
            elif request.client and request.client.host:
                ip = request.client.host[:64]
        except Exception:
            ip = None

        db.add(
            Auditoria(
                ticket_id=None,
                usuario_id=target.id,
                accion="CAMBIO_PASSWORD",
                valor_anterior=None,
                valor_nuevo={
                    "origen": "admin",
                    "admin_id": usuario.id,
                    "admin_username": usuario.username,
                },
                comentario=(
                    f"Contraseña reseteada por el administrador "
                    f"@{usuario.username} (id={usuario.id})."
                ),
                ip_origen=ip,
            )
        )
    except Exception:
        # Si la tabla de auditoría no está disponible, no bloqueamos.
        pass

    try:
        db.commit()
    except Exception:
        db.rollback()
        return _error_fragment(
            "No se pudo actualizar la contraseña. Intenta de nuevo."
        )

    payload = _json.dumps(
        {
            "message": f"Contraseña de @{target.username} actualizada correctamente.",
            "usuario_id": target.id,
        }
    )
    resp = Response(content="", status_code=200)
    resp.headers["HX-Trigger"] = "cambio-password-admin-ok"
    resp.headers["HX-Trigger-Evento"] = "cambio-password-admin-ok"
    resp.headers["HX-Trigger-Detalle"] = payload
    return resp
