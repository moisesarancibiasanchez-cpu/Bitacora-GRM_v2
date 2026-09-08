"""
Configuración central de la aplicación.
Soporta modo desarrollo (SQLite) y producción (PostgreSQL/Redis) vía variables de entorno.
"""
import os
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación cargada desde .env o variables de entorno."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Aplicación ===
    APP_NAME: str = "Bitácora GRM"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production-please"

    # === Base de datos ===
    # Si se define DATABASE_URL, se usa directamente. Si no, se construye.
    DATABASE_URL: str = "sqlite:///./bitacora_grm.db"

    # Configuración individual (usada para construir DATABASE_URL si no se define)
    POSTGRES_USER: str = "grm"
    POSTGRES_PASSWORD: str = "grm"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "bitacora_grm"

    # === Redis / Celery ===
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # === Autenticación ===
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 8

    # === ITSM / Reglas de Negocio ===
    # Roles disponibles en el sistema
    ROLES_DISPONIBLES: List[str] = [
        "administrador",
        "agente_senior",
        "agente",
        "solicitante",
        "observador",
    ]

    # === CORS ===
    CORS_ORIGINS: List[str] = ["*"]

    def get_database_url(self) -> str:
        """Devuelve la URL de BD; si no se configuró, construye la de PostgreSQL."""
        if self.DATABASE_URL and self.DATABASE_URL != "sqlite:///./bitacora_grm.db":
            return self.DATABASE_URL
        # Si se solicita SQLite explícitamente
        if os.getenv("USE_SQLITE", "false").lower() == "true":
            return "sqlite:///./bitacora_grm.db"
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Singleton de configuración."""
    return Settings()


settings = get_settings()
