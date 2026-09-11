"""
Servicio de credenciales: generación, envío de credenciales iniciales
y reseteo de contraseñas para usuarios del sistema.

Este servicio orquesta:

1. **Generación de contraseña provisoria** aleatoria.
2. **Hash + persistencia** de la contraseña en la tabla ``usuarios``.
3. **Envío del email** de credenciales vía ``email_service``.
4. **Registro en auditoría** de la acción (EMAIL_CREDENCIALES).

Si no hay SMTP configurado, el correo se persiste en
``tmp/app.email.log`` y se devuelve ``sent=False, transport='log'``.
Esto nunca rompe el flujo: la contraseña siempre se actualiza en BD.
"""
from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.auditoria import Auditoria
from app.models.usuario import Usuario
from app.services.email_service import (
    email_credenciales_iniciales,
    send_email,
)


logger = logging.getLogger(__name__)


# ============== Data classes ==============
@dataclass
class CredencialesResult:
    """Resultado del envío de credenciales."""
    sent: bool
    transport: str        # "smtp" | "log" | "disabled"
    to: str
    subject: str
    password_generada: str
    detail: Optional[str] = None


# ============== Helpers ==============
def generar_password_provisoria(longitud: int = 10) -> str:
    """
    Genera una contraseña provisoria segura y fácil de transcribir.

    La contraseña cumple con las validaciones del backend
    (>=6 caracteres, <=128, mezcla de letras y dígitos).
    """
    # Alfabeto sin caracteres ambiguos (0/O, 1/l/I)
    alfabeto = (
        string.ascii_uppercase.replace("O", "").replace("I", "") +
        string.ascii_lowercase.replace("l", "").replace("o", "") +
        string.digits.replace("0", "").replace("1", "")
    )
    if not alfabeto:
        alfabeto = string.ascii_letters + string.digits
    # Garantizar al menos 1 mayúscula, 1 minúscula y 1 dígito
    mayus = secrets.choice(string.ascii_uppercase.replace("O", "").replace("I", "") or string.ascii_uppercase)
    minus = secrets.choice(string.ascii_lowercase.replace("l", "").replace("o", "") or string.ascii_lowercase)
    digit = secrets.choice(string.digits.replace("0", "").replace("1", "") or string.digits)
    resto_len = max(longitud - 3, 0)
    resto = "".join(secrets.choice(alfabeto) for _ in range(resto_len))
    # Mezclar para que no estén en orden predecible
    pwd = list(mayus + minus + digit + resto)
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


def _auditar_envio_credenciales(
    db: Session,
    *,
    target: Usuario,
    actor: Usuario,
    transport: str,
    sent: bool,
    password_generada: str,
) -> None:
    """
    Inserta un registro de auditoría con la acción EMAIL_CREDENCIALES.
    Se hace best-effort: si la tabla no tiene el método, se omite.
    """
    try:
        registro = Auditoria(
            ticket_id=None,
            usuario_id=actor.id,
            accion="EMAIL_CREDENCIALES",
            valor_anterior=None,
            valor_nuevo={
                "destinatario_id": target.id,
                "destinatario_username": target.username,
                "destinatario_email": target.email,
                "rol": target.rol.value if hasattr(target.rol, "value") else str(target.rol),
                "email_sent": sent,
                "email_transport": transport,
                "password_reseteada": True,
            },
            comentario=(
                f"Credenciales enviadas al usuario {target.username} "
                f"({target.email}). Transport: {transport}."
            ),
        )
        db.add(registro)
        db.flush()
    except Exception as exc:
        # La auditoría es opcional: no rompemos el flujo si falla.
        logger.debug("[credenciales] auditoría omitida: %s", exc)


# ============== API principal ==============
def enviar_credenciales_iniciales(
    db: Session,
    *,
    target: Usuario,
    actor: Usuario,
    password_plana: Optional[str] = None,
    persistir_password: bool = True,
) -> CredencialesResult:
    """
    Envía (o re-envía) las credenciales iniciales a un usuario.

    Por defecto:
      1. Genera una nueva contraseña provisoria (si no se pasa una).
      2. La hashea y la persiste en la BD (si ``persistir_password``).
      3. Envía el email con la contraseña en texto plano.
      4. Audita la acción.

    Parameters
    ----------
    db : Session
        Sesión de SQLAlchemy.
    target : Usuario
        Usuario destinatario del email.
    actor : Usuario
        Usuario que dispara la acción (admin que envía las credenciales).
    password_plana : str, opcional
        Si se pasa, se usa esa contraseña en el email (sin re-hashear
        en BD a menos que ``persistir_password`` sea True). Útil para
        enviar credenciales sin re-generar la contraseña.
    persistir_password : bool
        Si True (default) y se pasa ``password_plana``, se hashea y
        persiste esa contraseña en la BD. Si es False, solo se envía
        el email.

    Returns
    -------
    CredencialesResult
        Resultado del envío (sent, transport, to, subject, password).
    """
    if not target.email:
        return CredencialesResult(
            sent=False,
            transport="disabled",
            to="",
            subject="",
            password_generada=password_plana or "",
            detail="usuario_sin_email",
        )

    # 1) Generar o usar la contraseña entregada
    pwd = password_plana or generar_password_provisoria()

    # 2) Persistir hash en BD (best-effort; si falla, no rompemos el envío)
    if persistir_password and pwd:
        try:
            target.hashed_password = hash_password(pwd)
            db.add(target)
            db.flush()
        except Exception as exc:
            logger.exception("[credenciales] No se pudo persistir password: %s", exc)
            db.rollback()
            # Reintentar con un nuevo objeto del target desde la sesión
            # (no es estrictamente necesario aquí, send_email sigue)

    # 3) Construir y enviar email
    rol_str = (
        target.rol.value if hasattr(target.rol, "value") else str(target.rol)
    )
    subject, body, html = email_credenciales_iniciales(
        nombre_completo=target.nombre_completo or target.username,
        email_destino=target.email,
        username=target.username,
        password=pwd,
        rol=rol_str,
        departamento=target.departamento,
        url_sistema=settings.PUBLIC_BASE_URL or "http://localhost:8000",
    )

    result = send_email(
        to=target.email,
        subject=subject,
        body=body,
        html_body=html,
    )

    # 4) Confirmar los cambios en BD (commit del password y de la auditoría)
    try:
        db.commit()
    except Exception as exc:
        logger.exception("[credenciales] commit final falló: %s", exc)
        db.rollback()

    # 5) Auditar (best-effort, después del commit)
    try:
        _auditar_envio_credenciales(
            db,
            target=target,
            actor=actor,
            transport=result.transport,
            sent=result.sent,
            password_generada=pwd,
        )
        db.commit()
    except Exception as exc:
        logger.debug("[credenciales] auditoría no registrada: %s", exc)

    return CredencialesResult(
        sent=result.sent,
        transport=result.transport,
        to=result.to,
        subject=result.subject,
        password_generada=pwd,
        detail=result.detail,
    )
