"""
Seguridad: hashing de contraseñas, autenticación básica, tokens de sesión.

Nota: usamos ``bcrypt`` directamente porque passlib 1.7.4 tiene
incompatibilidades con ``bcrypt>=4.0`` (``__about__`` deprecado y
``detect_wrap_bug`` que excede los 72 bytes). Mantenemos
``passlib`` sólo como dependencia declarada.
"""
import bcrypt
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError

from app.core.config import settings


# Rondas de bcrypt: 12 es un buen balance CPU/seguridad.
_BCRYPT_ROUNDS = 12


def _to_bcrypt_bytes(password: str) -> bytes:
    """Bcrypt sólo acepta hasta 72 bytes. Truncamos en bytes UTF-8."""
    if not isinstance(password, str):
        password = str(password)
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    """Genera un hash bcrypt de la contraseña (truncada a 72 bytes)."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_to_bcrypt_bytes(password), salt).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt (truncada a 72 bytes)."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_minutes: Optional[int] = None) -> str:
    """Crea un JWT con los datos del usuario."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(
        minutes=expires_minutes or settings.JWT_EXPIRATION_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decodifica y valida un JWT. Devuelve None si es inválido."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
