"""
Dependencias de FastAPI: autenticación y autorización.

Soporta 3 modos (en orden de prioridad):
1) Authorization: Bearer <jwt>
2) Cookie 'access_token' (sesión web persistente)
3) Header X-User-Id (modo demo / pruebas / integraciones internas)
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
    Resuelve el usuario actual siguiendo la cadena de prioridad:
      1) Authorization: Bearer <token> -> decodifica JWT
      2) Cookie 'access_token' -> decodifica JWT
      3) Header X-User-Id (modo demo / pruebas)
    """
    user_id = None

    # 1) Bearer token
    if credentials and credentials.credentials:
        payload = decode_access_token(credentials.credentials)
        if payload and "sub" in payload:
            try:
                user_id = int(payload["sub"])
            except (ValueError, TypeError):
                user_id = None

    # 2) Cookie de sesión
    if user_id is None:
        token = request.cookies.get("access_token")
        if token:
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                try:
                    user_id = int(payload["sub"])
                except (ValueError, TypeError):
                    user_id = None

    # 3) Modo demo: X-User-Id
    if user_id is None:
        x_user = request.headers.get("X-User-Id")
        if x_user:
            try:
                user_id = int(x_user)
            except (ValueError, TypeError):
                pass

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Inicie sesión o proporcione credenciales válidas.",
        )

    usuario = db.query(Usuario).filter(
        Usuario.id == user_id, Usuario.is_active == True  # noqa: E712
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


def require_admin(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency que exige rol Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere rol Administrador.",
        )
    return usuario
