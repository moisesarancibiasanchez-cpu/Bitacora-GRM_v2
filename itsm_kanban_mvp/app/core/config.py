"""Configuración central de la aplicación (cargada desde variables de entorno)."""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lee .env y expone la configuración validada por Pydantic v2."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "ITSM Kanban MVP"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str
    public_base_url: str = "http://localhost:8000"

    # DB
    database_url: str

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # JWT
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 480

    # Bootstrap admin
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    bootstrap_admin_email: str = "admin@example.com"


@lru_cache
def get_settings() -> Settings:
    """Cachea la configuración para no releer .env en cada llamada."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
