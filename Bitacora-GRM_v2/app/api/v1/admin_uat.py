"""
================================================================================
Admin UAT Import — Endpoints administrativos para cargar el Excel UAT.
================================================================================
Expone la funcionalidad de `app.services.uat_import` sobre HTTP, protegido por
rol Administrador.

Endpoints:
  POST /api/v1/admin/uat/dry-run   — Lee + transforma sin tocar la BD
  POST /api/v1/admin/uat/import    — Lee + transforma + inserta (idempotente)
  GET  /api/v1/admin/uat/status    — Estado actual de los tickets cargados

Uso típico desde curl:
  curl -X POST https://host/api/v1/admin/uat/import \\
       -H "Authorization: Bearer <JWT>" \\
       -F "file=@Consolidado_UAT_Cruce_GARANTIA_v3.xlsx"

NOTA DE SEGURIDAD: estos endpoints son exclusivos del rol Administrador.
El JWT debe pertenecer a un usuario con `rol = administrador`.
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.deps import require_admin
from app.db.session import get_db
from app.models.usuario import Usuario
from app.services import uat_import

log = logging.getLogger("admin_uat")

router = APIRouter(
    prefix="/admin/uat",
    tags=["Admin · UAT"],
    dependencies=[Depends(require_admin)],
)


# Límite de tamaño del Excel: 25 MB (deja margen sobre el archivo real ~700KB).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _read_upload(file: UploadFile) -> bytes:
    """Lee el UploadFile y valida que sea .xlsx y no exceda el tamaño máximo."""
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se recibió ningún archivo. Use multipart/form-data con el campo 'file'.",
        )

    fname = file.filename.lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".xlsm")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no soportado: '{file.filename}'. Se esperaba .xlsx / .xlsm.",
        )

    content = file.file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Archivo demasiado grande ({len(content):,} bytes). Máximo permitido: {MAX_UPLOAD_BYTES:,}.",
        )

    # Verificación rápida: ZIP magic (\x50\x4b\x03\x04 = PK..) — Excel = zip
    if not content[:4] == b"PK\x03\x04":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no parece ser un Excel válido (firma ZIP no encontrada).",
        )

    return content


@router.post("/dry-run")
def dry_run(
    file: UploadFile = File(..., description="Excel UAT (.xlsx) a previsualizar"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    """Lee y transforma el Excel sin insertar nada en la BD.

    Devuelve estadísticas de lo que SE INSERTARÍA si se llamara al endpoint
    ``/import`` con el mismo archivo. Útil para validar antes de ejecutar.
    """
    content = _read_upload(file)
    log.info(
        "dry-run UAT solicitado por usuario id=%s, archivo=%s (%d bytes)",
        usuario.id, file.filename, len(content),
    )

    try:
        report = uat_import.run_import(db, content, dry_run=True)
    except KeyError as e:
        # Hoja no encontrada
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hoja esperada no encontrada en el Excel: {e}. Verifique que contenga '{uat_import.HOJA}'.",
        )
    except Exception as e:
        log.exception("Error en dry-run UAT")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando el Excel: {e}",
        )

    report["filename"] = file.filename
    report["size_bytes"] = len(content)
    report["requested_by"] = usuario.username or usuario.email
    return report


@router.post("/import")
def run_import(
    file: UploadFile = File(..., description="Excel UAT (.xlsx) a importar"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    """Importa el Excel UAT a la tabla `tickets`.

    Es **IDEMPOTENTE**: si un `codigo` ya existe, se ignora
    (INSERT ... ON CONFLICT (codigo) DO NOTHING). Puede re-ejecutarse
    sin duplicar.

    Devuelve:
      - rows_leidas / rows_transformadas
      - inserted_attempts   (filas que se intentaron insertar)
      - inserted_confirmed  (diferencia antes/después = filas realmente nuevas)
      - pre_total / post_total (conteo total de tickets)
      - by_resultado / by_modulo (distribución de los registros transformados)
      - warnings / warnings_detalle (si los hubiera)
    """
    content = _read_upload(file)
    log.info(
        "Import UAT solicitado por usuario id=%s, archivo=%s (%d bytes)",
        usuario.id, file.filename, len(content),
    )

    try:
        report = uat_import.run_import(db, content, dry_run=False)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hoja esperada no encontrada en el Excel: {e}. Verifique que contenga '{uat_import.HOJA}'.",
        )
    except Exception as e:
        log.exception("Error en import UAT")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante la importación: {e}",
        )

    report["filename"] = file.filename
    report["size_bytes"] = len(content)
    report["requested_by"] = usuario.username or usuario.email
    return report


@router.get("/status")
def status_uat(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    """Resumen rápido del estado actual de los tickets UAT cargados.

    Filtra por ``ambiente='QA'`` y ``modulo IS NOT NULL`` (que son los
    tickets que el Excel Consolidado UAT produce al importarse).
    """
    total = db.execute(text(
        "SELECT count(*) FROM tickets WHERE ambiente='QA'"
    )).scalar() or 0

    by_resultado = db.execute(text(
        "SELECT COALESCE(resultado_pruebas, '(en blanco)') AS r, count(*) "
        "FROM tickets WHERE ambiente='QA' "
        "GROUP BY COALESCE(resultado_pruebas, '(en blanco)') "
        "ORDER BY count(*) DESC"
    )).fetchall()

    by_modulo = db.execute(text(
        "SELECT COALESCE(NULLIF(modulo, ''), '(en blanco)') AS m, count(*) "
        "FROM tickets WHERE ambiente='QA' "
        "GROUP BY COALESCE(NULLIF(modulo, ''), '(en blanco)') "
        "ORDER BY m"
    )).fetchall()

    return {
        "ambiente": "QA",
        "total": total,
        "by_resultado": [{"resultado": r, "total": c} for r, c in by_resultado],
        "by_modulo": [{"modulo": m, "total": c} for m, c in by_modulo],
        "consultado_por": usuario.username or usuario.email,
    }