"""Utilidades de seguridad: hashing de contraseñas y JWT."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
import bcrypt
from jose import jwt, JWTError

from .config import settings


# ---------- Password hashing (bcrypt directo, truncado a 72 bytes) ----------

def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(_to_bcrypt_bytes(password), salt).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------

def create_access_token(subject: str | int, extra_claims: dict[str, Any] | None = None) -> str:
    """Genera un JWT firmado con HS256."""
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expiration_minutes)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decodifica y valida un JWT. Retorna None si es inválido o expirado."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
