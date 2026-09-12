"""
Importar / Exportar tickets en múltiples formatos (solo Administrador).

Formatos soportados:
- Exportar: CSV, JSON, XLSX (Excel), TXT
- Importar: CSV, JSON, TXT (XLSX requiere librería adicional)

Los formatos siguen el mismo esquema:
  id, codigo, titulo, descripcion, tipo, prioridad, estado, asignado,
  etiquetas, fecha_vencimiento_sla, sla_cumplido, creado, actualizado

El importador es tolerante: crea tickets nuevos con código tipo
'GRM-IMP-XXXXXX' en el estado inicial del sistema.
"""
import csv
import io
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.estado import Estado
from app.models.ticket import Ticket, TipoIncidencia, Prioridad
from app.models.usuario import Usuario, RolUsuario

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tickets-ie", tags=["Importar/Exportar"])


# ============== Helpers ==============
def _require_admin(usuario: Usuario) -> Usuario:
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Requiere rol Administrador")
    return usuario


def _ticket_to_row(t: Ticket) -> Dict[str, Any]:
    return {
        "id": t.id,
        "codigo": t.codigo,
        "titulo": t.titulo,
        "descripcion": t.descripcion or "",
        "tipo": t.tipo.value if t.tipo else "",
        "prioridad": t.prioridad.value if t.prioridad else "",
        "estado": t.estado.nombre if t.estado else "",
        "asignado": t.asignado.nombre_completo if t.asignado else "",
        "etiquetas": ";".join(e.nombre for e in t.etiquetas),
        "fecha_vencimiento_sla": t.fecha_vencimiento_sla.isoformat() if t.fecha_vencimiento_sla else "",
        "sla_cumplido": (
            "Si" if t.sla_cumplido == 1 else
            "No" if t.sla_cumplido == 0 else "Pendiente"
        ),
        "creado": t.created_at.isoformat() if t.created_at else "",
        "actualizado": t.updated_at.isoformat() if t.updated_at else "",
    }


CAMPOS_IMPORT = [
    "titulo", "descripcion", "tipo", "prioridad",
    "asignado_username", "etiquetas",
]


# ============== EXPORTAR ==============
@router.get("/exportar/{formato}")
def exportar(
    formato: str,
    estado_id: Optional[int] = Query(None, description="Filtrar por estado"),
    etiqueta_id: Optional[int] = Query(None, description="Filtrar por etiqueta"),
    asignado_id: Optional[int] = Query(None, description="Filtrar por asignado"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Exporta tickets al formato solicitado. Solo Administrador."""
    _require_admin(usuario)
    formato = formato.lower()
    if formato not in {"csv", "json", "xlsx", "txt"}:
        raise HTTPException(status_code=400,
                            detail=f"Formato '{formato}' no soportado. Use: csv, json, xlsx, txt")

    # Construir query
    q = db.query(Ticket).filter(Ticket.archivado == False)  # noqa: E712
    if estado_id is not None:
        q = q.filter(Ticket.estado_id == estado_id)
    if asignado_id is not None:
        q = q.filter(Ticket.asignado_id == asignado_id)
    if etiqueta_id is not None:
        from app.models.etiqueta import ticket_etiquetas
        q = q.join(ticket_etiquetas, ticket_etiquetas.c.ticket_id == Ticket.id).filter(
            ticket_etiquetas.c.etiqueta_id == etiqueta_id
        )
    tickets = q.order_by(Ticket.created_at.desc()).limit(2000).all()
    filas = [_ticket_to_row(t) for t in tickets]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if formato == "csv":
        sio = io.StringIO()
        if filas:
            w = csv.DictWriter(sio, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)
        sio.seek(0)
        return StreamingResponse(
            iter([sio.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="tickets_{timestamp}.csv"'},
        )

    if formato == "json":
        sio = io.StringIO()
        json.dump(filas, sio, ensure_ascii=False, indent=2, default=str)
        sio.seek(0)
        return StreamingResponse(
            iter([sio.getvalue()]),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="tickets_{timestamp}.json"'},
        )

    if formato == "txt":
        sio = io.StringIO()
        cols = list(filas[0].keys()) if filas else list(_ticket_to_row(Ticket()).keys())
        sio.write("\t".join(cols) + "\n")
        for f in filas:
            sio.write("\t".join(str(f.get(c, "")) for c in cols) + "\n")
        sio.seek(0)
        return StreamingResponse(
            iter([sio.getvalue()]),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="tickets_{timestamp}.txt"'},
        )

    if formato == "xlsx":
        try:
            import openpyxl
            from openpyxl import Workbook
        except ImportError:
            raise HTTPException(status_code=500,
                                detail="openpyxl no instalado. Use CSV o JSON como alternativa.")
        wb = Workbook()
        ws = wb.active
        ws.title = "Tickets"
        if filas:
            cols = list(filas[0].keys())
            ws.append(cols)
            for fila in filas:
                ws.append([fila.get(c, "") for c in cols])
            # Encabezado en negrita
            for cell in ws[1]:
                cell.font = openpyxl.styles.Font(bold=True)
            # Ancho de columnas automático
            for col_idx, col_name in enumerate(cols, start=1):
                ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(
                    12, min(60, len(str(col_name)) + 4)
                )
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="tickets_{timestamp}.xlsx"'},
        )

    # No debería llegar aquí
    raise HTTPException(status_code=400, detail="Formato no implementado")


# ============== IMPORTAR ==============
@router.post("/importar/{formato}")
async def importar(
    formato: str,
    archivo: UploadFile = File(...),
    dry_run: bool = Form(False, description="Si True, valida pero no crea tickets"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Importa tickets desde un archivo. Solo Administrador."""
    _require_admin(usuario)
    formato = formato.lower()
    if formato not in {"csv", "json", "txt"}:
        raise HTTPException(status_code=400, detail=f"Formato '{formato}' no soportado para import")

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    filas: List[Dict[str, Any]] = []
    errores_parseo: List[str] = []

    try:
        if formato == "csv":
            texto = contenido.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(texto))
            filas = [dict(row) for row in reader if any((v or "").strip() for v in row.values())]
        elif formato == "json":
            data = json.loads(contenido.decode("utf-8", errors="replace"))
            if isinstance(data, list):
                filas = [row for row in data if isinstance(row, dict)]
            elif isinstance(data, dict):
                # Soportar {"tickets": [...]} o un único objeto
                if "tickets" in data and isinstance(data["tickets"], list):
                    filas = [row for row in data["tickets"] if isinstance(row, dict)]
                else:
                    filas = [data]
        elif formato == "txt":
            texto = contenido.decode("utf-8", errors="replace")
            lineas = [ln for ln in texto.splitlines() if ln.strip()]
            if not lineas:
                raise HTTPException(status_code=400, detail="Archivo TXT vacío")
            header = [c.strip() for c in lineas[0].split("\t")]
            for i, ln in enumerate(lineas[1:], start=2):
                vals = [v.strip() for v in ln.split("\t")]
                filas.append(dict(zip(header, vals)))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error parseando archivo de import: %s", e)
        raise HTTPException(status_code=400, detail=f"Error al parsear el archivo: {e}")

    if not filas:
        return {"total": 0, "creados": 0, "errores": ["El archivo no contiene filas válidas"]}

    # Estado inicial para los nuevos tickets
    estado_inicial = (
        db.query(Estado).filter(Estado.es_inicial == True).first()  # noqa: E712
    )
    if not estado_inicial:
        estado_inicial = db.query(Estado).order_by(Estado.orden).first()
    if not estado_inicial:
        raise HTTPException(status_code=500, detail="No hay estado inicial configurado en el sistema")

    # Mapear usuarios por username (para resolver asignado)
    usuarios_by_name = {
        u.username.lower(): u
        for u in db.query(Usuario).filter(Usuario.is_active == True).all()  # noqa: E712
    }

    # Mapear etiquetas
    from app.models.etiqueta import Etiqueta
    etiquetas_by_name = {
        e.nombre.lower(): e
        for e in db.query(Etiqueta).filter(Etiqueta.activo == True).all()  # noqa: E712
    }

    # Generador de código correlativo
    ultimo = db.query(func.max(Ticket.id)).scalar() or 0
    anio = datetime.utcnow().year

    creados = 0
    errores: List[str] = []

    for idx, fila in enumerate(filas, start=1):
        try:
            titulo = (fila.get("titulo") or "").strip()
            if not titulo:
                errores.append(f"Fila {idx}: falta 'titulo'")
                continue
            ultimo += 1
            codigo = f"GRM-IMP-{anio}-{ultimo:06d}"

            # Mapear tipo
            tipo_str = (fila.get("tipo") or "incidencia").strip().lower()
            try:
                tipo_enum = TipoIncidencia(tipo_str)
            except ValueError:
                tipo_enum = TipoIncidencia.INCIDENCIA

            # Mapear prioridad
            prio_str = (fila.get("prioridad") or "media").strip().lower()
            try:
                prio_enum = Prioridad(prio_str)
            except ValueError:
                prio_enum = Prioridad.MEDIA

            # Asignado
            asignado = None
            asig_username = (fila.get("asignado_username") or fila.get("asignado") or "").strip().lower()
            if asig_username:
                asignado = usuarios_by_name.get(asig_username)
                # Si no se encuentra por username, intentar por nombre
                if not asignado:
                    for u in usuarios_by_name.values():
                        if u.nombre_completo.lower() == asig_username:
                            asignado = u
                            break

            ticket = Ticket(
                codigo=codigo,
                titulo=titulo[:200],
                descripcion=(fila.get("descripcion") or "").strip()[:5000] or None,
                tipo=tipo_enum,
                prioridad=prio_enum,
                estado_id=estado_inicial.id,
                creador_id=usuario.id,
                asignado_id=asignado.id if asignado else None,
                sla_cumplido=-1,
            )
            db.add(ticket)
            db.flush()

            # Etiquetas
            et_str = (fila.get("etiquetas") or "").strip()
            if et_str:
                for et_name in [e.strip() for e in et_str.replace(";", ",").split(",") if e.strip()]:
                    et = etiquetas_by_name.get(et_name.lower())
                    if et and et not in ticket.etiquetas:
                        ticket.etiquetas.append(et)
            creados += 1
        except Exception as e:
            errores.append(f"Fila {idx}: {e}")
            logger.exception("Error importando fila %s", idx)

    if not dry_run and creados > 0:
        db.commit()

    return {
        "ok": True,
        "dry_run": dry_run,
        "total": len(filas),
        "creados": creados if not dry_run else 0,
        "errores": errores[:50],  # máx 50 errores en respuesta
        "total_errores": len(errores),
    }


@router.get("/formatos")
def formatos_disponibles(usuario: Usuario = Depends(get_current_user)):
    """Lista los formatos soportados para import/export."""
    _require_admin(usuario)
    return {
        "exportar": ["csv", "json", "xlsx", "txt"],
        "importar": ["csv", "json", "txt"],
        "columnas": [
            "id", "codigo", "titulo", "descripcion", "tipo", "prioridad",
            "estado", "asignado", "etiquetas", "fecha_vencimiento_sla",
            "sla_cumplido", "creado", "actualizado",
        ],
        "tipos_validos": [t.value for t in TipoIncidencia],
        "prioridades_validas": [p.value for p in Prioridad],
    }
