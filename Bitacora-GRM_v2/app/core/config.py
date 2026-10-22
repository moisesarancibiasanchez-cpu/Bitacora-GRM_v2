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

    # === Zona horaria operativa ===
    # Zona horaria usada para mostrar fechas al usuario. La BD siempre
    # almacena en UTC (naive, por compatibilidad con SQLite/PG); los
    # timestamps que se renderizan en HTML o se devuelven al frontend
    # se convierten a esta zona. Por defecto Chile continental, que
    # alterna entre UTC-3 (invierno) y UTC-4 (verano) y resuelve
    # automáticamente el cambio con ``zoneinfo``.
    APP_TIMEZONE: str = "America/Santiago"

    # === SMTP (envío de correos) ===
    # Si SMTP_HOST y SMTP_FROM están definidos, los correos se envían
    # vía SMTP real. Si no, se persisten en tmp/app.email.log (modo dev).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    # SMTP_USE_SSL=True fuerza SMTPS (TLS implícito, típico puerto 465).
    # Si se deja vacío/vacío, se autodetecta: puerto 465 → SSL, resto → STARTTLS.
    SMTP_USE_SSL: bool = False

    # === URL pública del sistema (para los correos) ===
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # === Backups de Base de Datos ===
    # Directorio donde se almacenan los archivos de backup (se crea si no existe).
    # En Railway es filesystem efímero, por lo que se recomienda apuntar a un
    # volumen persistente o a un servicio externo (S3, GCS) en producción.
    BACKUP_DIR: str = "backups"
    # Política de retención: cantidad de días que se conservan los backups.
    # Los backups más antiguos se eliminan automáticamente al finalizar el job diario.
    BACKUP_RETENTION_DAYS: int = 30
    # Hora del backup diario programado (formato 24h, hora local del Beat worker).
    # Por defecto 00:00 como pidió el usuario.
    BACKUP_DAILY_HOUR: int = 0
    BACKUP_DAILY_MINUTE: int = 0
    # Tamaño máximo permitido por archivo de backup en MB (protección anti-OOM).
    BACKUP_MAX_SIZE_MB: int = 2048

    # === Reporte diario de entregas ===
    # Hora (UTC) en la que Beat dispara la tarea ``generar_reporte_diario``.
    # Por defecto 18:00 UTC (≈ 15:00 hora Chile continental en invierno,
    # 14:00 en horario de verano). El admin puede cambiarlo desde la UI
    # ``/admin/reporte-entregas`` o definiendo estas env vars en Railway.
    REPORTE_ENTREGAS_HOUR: int = 18
    REPORTE_ENTREGAS_MINUTE: int = 0
    # Si False, la tarea programada registra entregas pero NO envía el
    # correo (útil para auditorías o para detener temporalmente el
    # envío mientras se ajusta la plantilla). El admin puede togglearlo
    # desde la UI.
    REPORTE_ENTREGAS_HABILITADO: bool = True

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
