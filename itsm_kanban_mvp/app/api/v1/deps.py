"""Dependencias de FastAPI: autenticación y DB."""
from __future__ import annotations
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.usuario import Usuario


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Usuario:
    """Lee la cookie `access_token` o el header `Authorization: Bearer`.

    Retorna el usuario autenticado. Lanza 401 si no hay sesión válida.
    """
    token: str | None = None

    # 1) Cookie
    token = request.cookies.get("access_token")
    # 2) Header Authorization
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin 'sub'")

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Subject inválido")

    usuario = db.get(Usuario, user_id_int)
    if not usuario or not usuario.activo:
        raise HTTPException(status_code=401, detail="Usuario no existe o está inactivo")

    return usuario
