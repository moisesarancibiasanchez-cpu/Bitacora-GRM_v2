"""
Servicio para gestionar el Reporte Diario de Entregas desde el panel admin.

Este módulo concentra TODA la lógica de negocio del reporte (CRUD de la
plantilla, gestión de destinatarios, regeneración, previsualización). La
capa de API en ``app/api/v1/reporte_entregas.py`` es un wrapper delgado
sobre este servicio.

Operaciones expuestas:
  - ``obtener_plantilla(db)``            → upsert a singleton id=1
  - ``guardar_plantilla(db, data, actor)``→ actualiza la fila singleton
  - ``listar_destinatarios(db)``
  - ``crear_destinatario(db, data, actor)``
  - ``actualizar_destinatario(db, id, data, actor)``
  - ``eliminar_destinatario(db, id, actor)``
  - ``toggle_destinatario(db, id, activo, actor)``
  - ``listar_estados_es_entrega(db)``
  - ``marcar_estado_es_entrega(db, estado_id, es_entrega, actor)``
  - ``listar_ultimos_reportes(db, limit)``
  - ``listar_entregas_por_dia(db, fecha)``
  - ``previsualizar_reporte(db, fecha)``
  - ``regenerar_reporte(db, fecha, actor)``

Cada acción que modifica estado audita en ``auditorias`` con la acción
``REPORTE_ENTREGAS_*`` para tener trazabilidad completa.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ===========================================================================
#  Plantilla
# ===========================================================================
def obtener_plantilla(db: Session):
    """Devuelve la fila singleton (id=1) de ``ReportePlantilla``.

    Si no existe, la crea con valores por defecto (idempotente).
    """
    from app.models.reporte_entregas import ReportePlantilla

    pl = db.query(ReportePlantilla).filter(ReportePlantilla.id == 1).first()
    if not pl:
        pl = ReportePlantilla(
            id=1,
            habilitado=True,
            asunto="[Bitácora GRM] Entregas del día {{fecha}} ({{cantidad}})",
            cuerpo_html="",
            cuerpo_texto="",
            firma="",
        )
        db.add(pl)
        db.commit()
        db.refresh(pl)
    return pl


def guardar_plantilla(
    db: Session,
    *,
    habilitado: bool,
    asunto: str,
    cuerpo_html: str,
    cuerpo_texto: str,
    firma: str,
    actor_id: Optional[int] = None,
):
    """Actualiza la plantilla singleton y registra auditoría."""
    from app.models.reporte_entregas import ReportePlantilla

    pl = obtener_plantilla(db)
    pl.habilitado = bool(habilitado)
    pl.asunto = (asunto or "").strip()[:255]
    pl.cuerpo_html = cuerpo_html or ""
    pl.cuerpo_texto = cuerpo_texto or ""
    pl.firma = firma or ""
    db.commit()
    db.refresh(pl)

    # Auditoría (best-effort)
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=None,
            usuario_id=actor_id,
            accion="REPORTE_ENTREGAS_PLANTILLA_EDITADA",
            valor_anterior=None,
            valor_nuevo={
                "habilitado": pl.habilitado,
                "asunto_len": len(pl.asunto),
                "cuerpo_html_len": len(pl.cuerpo_html),
                "cuerpo_texto_len": len(pl.cuerpo_texto),
                "firma_len": len(pl.firma),
            },
            comentario="Plantilla del reporte diario actualizada.",
            commit=True,
        )
    except Exception as exc:
        logger.debug("[reporte-entregas-svc] auditoría opcional: %s", exc)
    return pl


# ===========================================================================
#  Destinatarios
# ===========================================================================
def listar_destinatarios(db: Session):
    from app.models.reporte_entregas import ReporteDestinatario

    return (
        db.query(ReporteDestinatario)
        .order_by(ReporteDestinatario.activo.desc(), ReporteDestinatario.email.asc())
        .all()
    )


def crear_destinatario(
    db: Session,
    *,
    email: str,
    nombre: Optional[str] = None,
    rol: Optional[str] = None,
    usuario_id: Optional[int] = None,
    activo: bool = True,
    notas: Optional[str] = None,
    actor_id: Optional[int] = None,
):
    from app.models.reporte_entregas import ReporteDestinatario
    from app.models.usuario import Usuario

    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        raise ValueError("Email inválido")

    # Si hay duplicado, devolver el existente con flag de actualizado=False.
    existente = (
        db.query(ReporteDestinatario)
        .filter(ReporteDestinatario.email == email_norm)
        .first()
    )
    if existente:
        existente.nombre = nombre or existente.nombre
        existente.rol = rol or existente.rol
        if usuario_id is not None:
            existente.usuario_id = usuario_id
        existente.notas = notas if notas is not None else existente.notas
        existente.activo = bool(activo)
        db.commit()
        db.refresh(existente)
        _audit_destinatario(
            db, "REPORTE_ENTREGAS_DEST_EDITADO", existente, actor_id,
            nota="Editado via upsert",
        )
        return existente, False

    # Validar FK a usuario si viene
    if usuario_id is not None:
        usuario = (
            db.query(Usuario).filter(Usuario.id == usuario_id).first()
        )
        if not usuario:
            raise ValueError(f"usuario_id={usuario_id} no existe")

    nuevo = ReporteDestinatario(
        email=email_norm,
        nombre=(nombre or "").strip()[:120] or None,
        rol=(rol or "").strip()[:40] or None,
        usuario_id=usuario_id,
        activo=bool(activo),
        notas=notas,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    _audit_destinatario(
        db, "REPORTE_ENTREGAS_DEST_CREADO", nuevo, actor_id,
        nota="Nuevo destinatario",
    )
    return nuevo, True


def toggle_destinatario(
    db: Session,
    *,
    destinatario_id: int,
    activo: bool,
    actor_id: Optional[int] = None,
):
    from app.models.reporte_entregas import ReporteDestinatario

    dest = (
        db.query(ReporteDestinatario)
        .filter(ReporteDestinatario.id == destinatario_id)
        .first()
    )
    if not dest:
        raise ValueError(f"destinatario_id={destinatario_id} no existe")
    dest.activo = bool(activo)
    db.commit()
    db.refresh(dest)
    _audit_destinatario(
        db, "REPORTE_ENTREGAS_DEST_TOGGLE", dest, actor_id,
        nota=f"activo={dest.activo}",
    )
    return dest


def eliminar_destinatario(
    db: Session,
    *,
    destinatario_id: int,
    actor_id: Optional[int] = None,
):
    from app.models.reporte_entregas import ReporteDestinatario

    dest = (
        db.query(ReporteDestinatario)
        .filter(ReporteDestinatario.id == destinatario_id)
        .first()
    )
    if not dest:
        raise ValueError(f"destinatario_id={destinatario_id} no existe")
    snapshot = {
        "id": dest.id, "email": dest.email,
        "nombre": dest.nombre, "rol": dest.rol,
        "usuario_id": dest.usuario_id,
    }
    db.delete(dest)
    db.commit()
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=None,
            usuario_id=actor_id,
            accion="REPORTE_ENTREGAS_DEST_ELIMINADO",
            valor_anterior=snapshot,
            valor_nuevo=None,
            comentario=f"Destinatario eliminado: {snapshot['email']}",
            commit=True,
        )
    except Exception as exc:
        logger.debug("[reporte-entregas-svc] auditoría opcional: %s", exc)
    return snapshot


def _audit_destinatario(db, action, dest, actor_id, nota=""):
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=None,
            usuario_id=actor_id,
            accion=action,
            valor_anterior=None,
            valor_nuevo={
                "id": dest.id,
                "email": dest.email,
                "rol": dest.rol,
                "activo": dest.activo,
            },
            comentario=nota or f"{action}: {dest.email}",
            commit=True,
        )
    except Exception as exc:
        logger.debug("[reporte-entregas-svc] auditoría opcional: %s", exc)


# ===========================================================================
#  Estados
# ===========================================================================
def listar_estados_es_entrega(db: Session):
    """Devuelve TODOS los estados (para el admin marcar/desmarcar)."""
    from app.models.estado import Estado

    return (
        db.query(Estado)
        .order_by(Estado.orden.asc(), Estado.nombre.asc())
        .all()
    )


def marcar_estado_es_entrega(
    db: Session,
    *,
    estado_id: int,
    es_entrega: bool,
    actor_id: Optional[int] = None,
):
    """Marca/desmarca un estado como terminal de entrega."""
    from app.models.estado import Estado

    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        raise ValueError(f"estado_id={estado_id} no existe")
    anterior = bool(estado.es_entrega)
    estado.es_entrega = bool(es_entrega)
    db.commit()
    db.refresh(estado)
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=None,
            usuario_id=actor_id,
            accion="REPORTE_ENTREGAS_ESTADO_TOGGLE",
            valor_anterior={"es_entrega": anterior},
            valor_nuevo={
                "es_entrega": estado.es_entrega,
                "estado_id": estado.id,
                "estado_nombre": estado.nombre,
            },
            comentario=(
                f"Estado «{estado.nombre}»: "
                f"es_entrega {anterior} → {estado.es_entrega}"
            ),
            commit=True,
        )
    except Exception as exc:
        logger.debug("[reporte-entregas-svc] auditoría opcional: %s", exc)
    return estado


# ===========================================================================
#  Listado de entregas / reportes
# ===========================================================================
def listar_ultimas_entregas(db: Session, *, limit: int = 100):
    from app.models.reporte_entregas import ReporteEntregaDiaria

    return (
        db.query(ReporteEntregaDiaria)
        .order_by(ReporteEntregaDiaria.fecha_entrega.desc())
        .limit(limit)
        .all()
    )


def listar_entregas_por_dia(db: Session, *, fecha_iso: str):
    """Devuelve todas las entregas de un día (formato YYYY-MM-DD)."""
    from app.models.reporte_entregas import ReporteEntregaDiaria
    from sqlalchemy import func

    try:
        fecha = date.fromisoformat(fecha_iso)
    except ValueError:
        raise ValueError(f"fecha inválida: {fecha_iso}")
    # Compatible PG/SQLite: ``func.date(col)`` funciona en ambos.
    return (
        db.query(ReporteEntregaDiaria)
        .filter(func.date(ReporteEntregaDiaria.fecha_entrega) == fecha)
        .order_by(ReporteEntregaDiaria.fecha_entrega.asc())
        .all()
    )


def resumen_entregas_por_dia(db: Session, *, dias: int = 7):
    """Resumen agregado: ``[{fecha: 'YYYY-MM-DD', total: int, enviadas: int}, ...]``
    Para los últimos N días calendario (incluyendo hoy).
    """
    from app.models.reporte_entregas import ReporteEntregaDiaria
    from sqlalchemy import func

    dia_col = func.date(ReporteEntregaDiaria.fecha_entrega).label("dia")
    rows = (
        db.query(
            dia_col,
            func.count(ReporteEntregaDiaria.id).label("total"),
            func.sum(
                func.cast(
                    ReporteEntregaDiaria.reporte_enviado_en.isnot(None),
                    Integer,
                )
            ).label("enviadas"),
        )
        .select_from(ReporteEntregaDiaria)
        .filter(ReporteEntregaDiaria.fecha_entrega
                >= func.current_date() - timedelta(days=dias))
        .group_by(dia_col)
        .order_by(dia_col.desc())
        .all()
    )
    resumen = []
    for r in rows:
        resumen.append({
            "fecha": str(r.dia),
            "total": int(r.total or 0),
            "enviadas": int(r.enviadas or 0),
        })
    return resumen


# ===========================================================================
#  Previsualización y regeneración
# ===========================================================================
def previsualizar_reporte(
    db: Session,
    *,
    fecha_iso: Optional[str] = None,
    base_url: str = "",
) -> dict:
    """Devuelve el HTML y texto plano del reporte SIN enviarlo.

    Útil para la UI admin "ver cómo quedaría".
    """
    try:
        fecha = date.fromisoformat(fecha_iso) if fecha_iso else datetime.utcnow().date()
    except ValueError:
        raise ValueError(f"fecha inválida: {fecha_iso}")

    entregas = listar_entregas_por_dia(db, fecha_iso=fecha.isoformat())
    pl = obtener_plantilla(db)
    # Renderizar con el mismo helper que la tarea Celery.
    # Import lazy para evitar import circular.
    from app.tasks.entregas import _format_fecha_larga, _render_tabla_html, _render_tabla_texto
    fecha_legible = _format_fecha_larga(fecha)
    tabla_html = _render_tabla_html(entregas, base_url=base_url)
    tabla_texto = _render_tabla_texto(entregas)
    cantidad = len(entregas)

    asunto = (pl.asunto or "[Bitácora GRM] Entregas del día {{fecha}} ({{cantidad}})").format(
        fecha=fecha_legible, cantidad=cantidad,
        tabla_html=tabla_html, tabla_texto=tabla_texto,
    )
    cuerpo_html = (pl.cuerpo_html or "").format(
        fecha=fecha_legible, cantidad=cantidad,
        tabla_html=tabla_html, tabla_texto=tabla_texto,
    )
    cuerpo_texto = (pl.cuerpo_texto or "").format(
        fecha=fecha_legible, cantidad=cantidad,
        tabla_html=tabla_html, tabla_texto=tabla_texto,
    )
    firma = pl.firma or ""

    return {
        "ok": True,
        "fecha": fecha.isoformat(),
        "fecha_legible": fecha_legible,
        "cantidad": cantidad,
        "asunto": asunto,
        "cuerpo_html": cuerpo_html + ("\n" + firma if firma else ""),
        "cuerpo_texto": cuerpo_texto + ("\n\n" + firma if firma else ""),
        "entregas": [
            {
                "id": e.id,
                "ticket_codigo": e.ticket_codigo,
                "ticket_titulo": e.ticket_titulo,
                "estado_destino_nombre": e.estado_destino_nombre,
                "asignado_nombre": e.asignado_nombre,
                "fecha_entrega": (
                    e.fecha_entrega.isoformat() if e.fecha_entrega else None
                ),
                "reporte_enviado_en": (
                    e.reporte_enviado_en.isoformat() if e.reporte_enviado_en else None
                ),
            }
            for e in entregas
        ],
    }


def regenerar_reporte(
    db: Session,
    *,
    fecha_iso: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> dict:
    """Encola la tarea Celery ``generar_reporte_diario`` para la fecha dada."""
    try:
        from app.tasks.entregas import generar_reporte_diario
        r = generar_reporte_diario.delay(fecha_iso)
        try:
            from app.services.auditoria_service import registrar_auditoria
            registrar_auditoria(
                db=db,
                ticket_id=None,
                usuario_id=actor_id,
                accion="REPORTE_ENTREGAS_REGENERAR",
                valor_anterior=None,
                valor_nuevo={
                    "fecha": fecha_iso or "hoy",
                    "task_id": r.id,
                },
                comentario=(
                    f"Regeneración manual del reporte {fecha_iso or 'hoy'} "
                    f"(task_id={r.id})."
                ),
                commit=True,
            )
        except Exception as exc:
            logger.debug("[reporte-entregas-svc] auditoría opcional: %s", exc)
        return {
            "ok": True,
            "task_id": r.id,
            "fecha": fecha_iso or datetime.utcnow().date().isoformat(),
        }
    except Exception as exc:
        logger.exception("[reporte-entregas-svc] No se pudo encolar: %s", exc)
        return {
            "ok": False,
            "error": str(exc),
            "fecha": fecha_iso or datetime.utcnow().date().isoformat(),
        }