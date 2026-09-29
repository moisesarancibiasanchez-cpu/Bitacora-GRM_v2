"""
Endpoints REST para gestión de respaldos de Base de Datos.

Estos endpoints exponen la funcionalidad del :class:`BackupService` vía HTTP,
pensados para ser consumidos desde la UI Butler · Automatizaciones o desde
integraciones externas (curl, Postman, scripts, etc.).

Todos los endpoints requieren autenticación (JWT cookie o header).

Resumen de endpoints:

- ``GET    /api/v1/butler/backup/status``    -> estado del sistema + próximo run.
- ``GET    /api/v1/butler/backup/list``      -> lista los archivos .gz disponibles.
- ``POST   /api/v1/butler/backup/run``       -> dispara un backup manual ahora.
- ``GET    /api/v1/butler/backup/download/<file>`` -> descarga el .gz.
- ``DELETE /api/v1/butler/backup/<file>``    -> elimina un backup específico.
- ``POST   /api/v1/butler/backup/cleanup``   -> purga según política de retención.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario
from app.services.backup_service import (
    BackupService,
    get_backup_service,
)
from app.tasks.backup_tasks import run_backup_sync


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/butler/backup",
    tags=["Butler · Backups"],
)


# ============================================================
# Schemas
# ============================================================
class BackupRunRequest(BaseModel):
    note: Optional[str] = Field(
        default="manual",
        max_length=64,
        description="Etiqueta corta que se persiste en la metadata del backup",
    )
    async_task: bool = Field(
        default=False,
        description="Si True, encola en Celery en vez de ejecutar sincrónicamente",
    )


class BackupCleanupRequest(BaseModel):
    retention_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=3650,
        description="Días a conservar (None = usar BACKUP_RETENTION_DAYS de settings)",
    )


class BackupRunResponse(BaseModel):
    ok: bool
    started_at: str
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    task_id: Optional[str] = None
    cleanup: Optional[Dict[str, Any]] = None


class BackupStatusResponse(BaseModel):
    backup_dir: str
    backup_dir_exists: bool
    backup_dir_writable: bool
    retention_days: int
    max_size_mb: int
    engine: str
    pg_dump_available: bool
    total_backups: int
    total_size_bytes: int
    last_backup: Optional[Dict[str, Any]] = None
    schedule: Dict[str, int]


class BackupListItem(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str
    engine: str
    duration_seconds: Optional[float] = None
    schema_version: str = ""
    notes: str = ""
    metadata_path: Optional[str] = None


# ============================================================
# Permisos
# ============================================================
def _require_admin(usuario: Usuario) -> None:
    """Los backups son sensibles: solo administrador o agente_senior."""
    rol = (usuario.rol.value if hasattr(usuario.rol, "value") else str(usuario.rol)).lower()
    if rol not in {"administrador", "agente_senior"}:
        raise HTTPException(
            status_code=403,
            detail="Se requiere rol administrador o agente_senior para acceder a backups",
        )


# ============================================================
# Endpoints
# ============================================================
@router.get("/status", response_model=BackupStatusResponse)
def get_status(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Any:
    """Estado general del sistema de backups."""
    _require_admin(usuario)
    service = get_backup_service()
    return service.status()


@router.get("/list", response_model=List[BackupListItem])
def list_backups(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Any:
    """Lista los archivos de backup disponibles (ordenados por fecha desc)."""
    _require_admin(usuario)
    service = get_backup_service()
    return service.list_backups()


@router.post("/run", response_model=BackupRunResponse)
def run_backup(
    datos: BackupRunRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Any:
    """Dispara un backup manual.

    Por defecto se ejecuta de forma sincrónica y devuelve el resultado
    estructurado. Si ``async_task=True``, encola en Celery y devuelve el
    ``task_id`` para consultar el estado después.
    """
    _require_admin(usuario)
    note = (datos.note or "manual").strip()[:64] or "manual"

    if datos.async_task:
        try:
            from app.tasks.backup_tasks import backup_database_manual
            async_result = backup_database_manual.apply_async(kwargs={"note": note})
            return BackupRunResponse(
                ok=True,
                started_at=__import__("datetime").datetime.utcnow().isoformat(),
                task_id=async_result.id,
            )
        except Exception as e:
            logger.exception("No se pudo encolar backup en Celery")
            # Caer a ejecución síncrona como fallback
            payload = run_backup_sync(note=note)
            return BackupRunResponse(**payload)

    payload = run_backup_sync(note=note)
    return BackupRunResponse(**payload)


@router.get("/download/{filename}")
def download_backup(
    filename: str,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Descarga el archivo .gz de un backup específico."""
    _require_admin(usuario)
    service = get_backup_service()
    path = service.get_backup_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail=f"Backup '{filename}' no encontrado")
    # El media_type correcto para .gz es application/gzip
    media_type = "application/gzip"
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type=media_type,
    )


@router.delete("/{filename}")
def delete_backup(
    filename: str,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    """Elimina un backup específico y su metadata."""
    _require_admin(usuario)
    service = get_backup_service()
    ok, msg = service.delete_backup(filename)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/cleanup")
def cleanup_old(
    datos: BackupCleanupRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    """Purga backups más antiguos que ``retention_days`` (default=settings)."""
    _require_admin(usuario)
    service = get_backup_service()
    res = service.cleanup_old_backups(retention_days=datos.retention_days)
    return res
