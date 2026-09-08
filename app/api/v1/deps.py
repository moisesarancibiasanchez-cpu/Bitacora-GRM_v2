"""
Dependencias de FastAPI: autenticación y autorización.
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario


security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Usuario:
    """
    Resuelve el usuario actual:
    1. Si viene Authorization: Bearer <token> -> decodifica JWT.
    2. Si no, toma el header `X-User-Id` (modo demo / pruebas).
    """
    user_id = None
    if credentials and credentials.credentials:
        payload = decode_access_token(credentials.credentials)
        if payload and "sub" in payload:
            user_id = int(payload["sub"])

    if user_id is None:
        # Modo demo: permite pasar X-User-Id
        x_user = request.headers.get("X-User-Id")
        if x_user:
            try:
                user_id = int(x_user)
            except ValueError:
                pass

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Proporcione Authorization Bearer o X-User-Id.",
        )

    usuario = db.query(Usuario).filter(
        Usuario.id == user_id, Usuario.is_active == True
    ).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
        )
    return usuario


def require_role(*roles: RolUsuario):
    """Fabrica un dependency que exige uno de los roles dados."""
    def _checker(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requiere rol: {', '.join(r.value for r in roles)}",
            )
        return usuario
    return _checker
