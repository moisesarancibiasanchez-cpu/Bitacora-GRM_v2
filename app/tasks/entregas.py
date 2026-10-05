"""
Tareas Celery para el Reporte Diario de Entregas.

Hay dos tareas:

1. ``registrar_entrega_diaria`` (idempotente):
    Disparada por el hook de ``ticket_service.cambiar_estado`` cuando el
    ticket cae en un estado marcado como ``es_entrega=True``. Inserta
    una fila en ``reporte_entregas_diarias`` con snapshots del ticket.
    Es idempotente gracias a ``UNIQUE(historial_estado_id)``: usar
    ``INSERT ... ON CONFLICT DO NOTHING`` (PG) o ``INSERT OR IGNORE``
    (SQLite) garantiza que un reintento no cree duplicados.

2. ``generar_reporte_diario`` (ejecutada por beat):
    Construye y envía el correo diario con todas las entregas registradas
    en el día objetivo (default: hoy UTC). Usa la plantilla singleton
    ``reporte_plantilla`` y la lista de destinatarios activos.

Las tareas son ``bind=True`` con ``max_retries`` para tolerar fallos
transitorios de BD/Redis. Cada tarea abre y cierra su propia
``SessionLocal`` (no acepta sesiones externas) para evitar sesiones
compartidas entre el request HTTP y el worker.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)


# ===========================================================================
#  1) REGISTRAR una transición a estado de entrega (idempotente)
# ===========================================================================
@celery_app.task(
    name="app.tasks.entregas.registrar_entrega_diaria",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def registrar_entrega_diaria(self, ticket_id: int, historial_estado_id: int) -> dict:
    """
    Registra una transición a un estado de entrega en la tabla
    ``reporte_entregas_diarias``. Es idempotente: si la misma
    transición (mismo ``historial_estado_id``) ya fue registrada, NO
    se duplica.

    Parameters
    ----------
    ticket_id : int
        ID del ticket que cambió de estado.
    historial_estado_id : int
        ID del registro en ``historial_estados`` que documenta el
        cambio. Es la clave de idempotencia.

    Returns
    -------
    dict
        ``{
            "ok": True|False,
            "registrado": bool,           # True si se insertó una fila nueva
            "ticket_id": int,
            "historial_estado_id": int,
            "motivo_skip": str | None,    # p.ej. "estado_no_es_entrega"
        }``
    """
    db = SessionLocal()
    try:
        # 1) Leer el historial + ticket + estado destino en una sola query.
        from app.models.reporte_entregas import ReporteEntregaDiaria
        from app.models.ticket import Ticket, HistorialEstado

        historial = (
            db.query(HistorialEstado)
            .filter(HistorialEstado.id == historial_estado_id)
            .first()
        )
        if not historial:
            logger.warning(
                "[entregas:registrar] historial_estado_id=%s no existe",
                historial_estado_id,
            )
            return {
                "ok": False,
                "registrado": False,
                "motivo_skip": "historial_no_existe",
                "ticket_id": ticket_id,
                "historial_estado_id": historial_estado_id,
            }

        ticket = (
            db.query(Ticket).filter(Ticket.id == historial.ticket_id).first()
        )
        if not ticket:
            logger.warning(
                "[entregas:registrar] ticket_id=%s no existe", historial.ticket_id,
            )
            return {
                "ok": False,
                "registrado": False,
                "motivo_skip": "ticket_no_existe",
                "ticket_id": historial.ticket_id,
                "historial_estado_id": historial_estado_id,
            }

        estado_destino = historial.estado_destino
        # Doble check: el estado destino debe seguir marcado como es_entrega.
        # Si el admin lo desmarcó entre la transición y la ejecución de la
        # tarea, NO registramos (consistente con la configuración actual).
        if not estado_destino or not getattr(estado_destino, "es_entrega", False):
            logger.info(
                "[entregas:registrar] ticket=%s historial=%s → estado destino "
                "('%s') ya no es entrega; se omite el registro.",
                ticket.id, historial.id,
                estado_destino.nombre if estado_destino else "?",
            )
            return {
                "ok": True,
                "registrado": False,
                "motivo_skip": "estado_no_es_entrega",
                "ticket_id": ticket.id,
                "historial_estado_id": historial.id,
            }

        # 2) Snapshots al momento del cambio (no se recalculan luego).
        asignado = ticket.asignado
        asignado_email = asignado.email if (asignado and asignado.email) else None
        asignado_nombre = (
            asignado.nombre_completo if (asignado and asignado.nombre_completo)
            else (asignado.username if asignado else None)
        )

        # 4) INSERT idempotente: UNIQUE(historial_estado_id) garantiza que
        #    la misma transición nunca se registre dos veces.
        try:
            nueva = ReporteEntregaDiaria(
                ticket_id=ticket.id,
                historial_estado_id=historial.id,
                estado_destino_id=estado_destino.id,
                usuario_cambio_id=historial.usuario_id,
                ticket_codigo=ticket.codigo or "",
                ticket_titulo=ticket.titulo or "",
                estado_destino_nombre=estado_destino.nombre or "",
                asignado_email=asignado_email,
                asignado_nombre=asignado_nombre,
                fecha_entrega=historial.fecha or datetime.utcnow(),
                reporte_enviado_en=None,
            )
            db.add(nueva)
            db.commit()
            logger.info(
                "[entregas:registrar] ticket=%s historial=%s → registrado "
                "(estado='%s', fecha=%s)",
                ticket.id, historial.id, estado_destino.nombre,
                historial.fecha,
            )
            return {
                "ok": True,
                "registrado": True,
                "motivo_skip": None,
                "ticket_id": ticket.id,
                "historial_estado_id": historial.id,
                "reporte_id": nueva.id,
            }
        except IntegrityError:
            # Conflicto por UNIQUE(historial_estado_id): la transición ya
            # estaba registrada. Es lo esperado en reintentos.
            db.rollback()
            logger.info(
                "[entregas:registrar] ticket=%s historial=%s ya estaba "
                "registrado (idempotencia OK).",
                ticket.id, historial.id,
            )
            return {
                "ok": True,
                "registrado": False,
                "motivo_skip": "ya_registrado",
                "ticket_id": ticket.id,
                "historial_estado_id": historial.id,
            }
    except Exception as exc:
        logger.exception(
            "[entregas:registrar] Error registrando entrega ticket=%s "
            "historial=%s: %s",
            ticket_id, historial_estado_id, exc,
        )
        try:
            db.rollback()
        except Exception:
            pass
        try:
            raise self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            return {
                "ok": False,
                "registrado": False,
                "motivo_skip": "max_retries_exceeded",
                "error": str(exc),
                "ticket_id": ticket_id,
                "historial_estado_id": historial_estado_id,
            }
    finally:
        db.close()


# ===========================================================================
#  2) GENERAR y ENVIAR el reporte diario
# ===========================================================================
@celery_app.task(
    name="app.tasks.entregas.generar_reporte_diario",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def generar_reporte_diario(self, fecha_objetivo: Optional[str] = None) -> dict:
    """
    Genera y envía el reporte diario de entregas para la fecha indicada
    (default: hoy UTC).

    - Si la plantilla está deshabilitada (``habilitado=False``), NO envía
      pero igual marca las entregas con ``reporte_enviado_en = NULL``
      (estado consistente).
    - Construye el HTML y texto plano a partir de la plantilla.
    - Envía a todos los destinatarios activos.
    - Marca ``reporte_enviado_en`` con NOW() en las entregas del día.

    Parameters
    ----------
    fecha_objetivo : str | None
        Fecha objetivo en formato ISO (``"YYYY-MM-DD"``). Si es None,
        se usa la fecha actual UTC.

    Returns
    -------
    dict
        ``{
            "ok": bool,
            "fecha_objetivo": str,
            "cantidad": int,
            "destinatarios": int,
            "emails_enviados": int,
            "errores": list[str],
            "skipped_reason": str | None,
        }``
    """
    from app.models.reporte_entregas import (
        ReportePlantilla,
        ReporteDestinatario,
        ReporteEntregaDiaria,
    )
    from app.models.usuario import Usuario
    from app.services.email_service import send_email
    from app.core.config import settings

    db = SessionLocal()
    try:
        # === 1) Plantilla singleton ===
        plantilla = (
            db.query(ReportePlantilla).filter(ReportePlantilla.id == 1).first()
        )
        if not plantilla:
            # Crear la fila por defecto (idempotente).
            plantilla = ReportePlantilla(
                id=1,
                habilitado=True,
                asunto="[Bitácora GRM] Entregas del día {{fecha}} ({{cantidad}})",
                cuerpo_html=_PLANTILLA_HTML_DEFAULT,
                cuerpo_texto=_PLANTILLA_TEXTO_DEFAULT,
                firma=_FIRMA_DEFAULT,
            )
            db.add(plantilla)
            db.commit()
            db.refresh(plantilla)

        # === 2) Calcular fecha objetivo ===
        if fecha_objetivo:
            try:
                fecha = date.fromisoformat(fecha_objetivo)
            except ValueError:
                fecha = datetime.utcnow().date()
        else:
            fecha = datetime.utcnow().date()

        # === 3) Cargar entregas del día ===
        #     La comparación fecha_entrega::date = :fecha funciona en PG
        #     y SQLite (ambos soportan CAST AS DATE).
        entregas = (
            db.query(ReporteEntregaDiaria)
            .filter(text("fecha_entrega::date = :f").bindparams(f=fecha))
            .order_by(ReporteEntregaDiaria.fecha_entrega.asc())
            .all()
        )
        cantidad = len(entregas)

        # === 4) Si no hay entregas, NO enviar (a menos que se fuerce). ===
        if cantidad == 0:
            logger.info(
                "[entregas:reporte] Sin entregas en %s; no se envía correo.",
                fecha,
            )
            return {
                "ok": True,
                "fecha_objetivo": fecha.isoformat(),
                "cantidad": 0,
                "destinatarios": 0,
                "emails_enviados": 0,
                "errores": [],
                "skipped_reason": "sin_entregas",
            }

        # === 5) Si la plantilla está deshabilitada, NO enviar ===
        if not plantilla.habilitado:
            logger.info(
                "[entregas:reporte] Plantilla deshabilitada; %d entregas "
                "registradas pero no se envía correo.",
                cantidad,
            )
            return {
                "ok": True,
                "fecha_objetivo": fecha.isoformat(),
                "cantidad": cantidad,
                "destinatarios": 0,
                "emails_enviados": 0,
                "errores": [],
                "skipped_reason": "plantilla_deshabilitada",
            }

        # === 6) Construir contenido ===
        fecha_legible = _format_fecha_larga(fecha)
        tabla_html = _render_tabla_html(entregas, base_url=settings.PUBLIC_BASE_URL)
        tabla_texto = _render_tabla_texto(entregas)

        asunto = (plantilla.asunto or _ASUNTO_DEFAULT).format(
            fecha=fecha_legible, cantidad=cantidad, tabla_html=tabla_html,
            tabla_texto=tabla_texto,
        )
        cuerpo_html = (plantilla.cuerpo_html or _PLANTILLA_HTML_DEFAULT).format(
            fecha=fecha_legible, cantidad=cantidad, tabla_html=tabla_html,
            tabla_texto=tabla_texto,
        )
        cuerpo_texto = (plantilla.cuerpo_texto or _PLANTILLA_TEXTO_DEFAULT).format(
            fecha=fecha_legible, cantidad=cantidad, tabla_html=tabla_html,
            tabla_texto=tabla_texto,
        )
        firma = plantilla.firma or _FIRMA_DEFAULT

        # Añadir firma al final (en ambas versiones)
        cuerpo_html_full = cuerpo_html + "\n" + (firma or "")
        cuerpo_texto_full = cuerpo_texto + "\n\n" + (firma or "")

        # === 7) Destinatarios activos ===
        destinatarios_q = (
            db.query(ReporteDestinatario)
            .filter(ReporteDestinatario.activo == True)  # noqa: E712
            .all()
        )
        # Filtrar: si tiene usuario_id, el usuario debe estar activo.
        destinatarios = []
        for d in destinatarios_q:
            if not d.email:
                continue
            if d.usuario_id is not None:
                usuario = (
                    db.query(Usuario).filter(Usuario.id == d.usuario_id).first()
                )
                if not usuario or not getattr(usuario, "is_active", True):
                    continue
            destinatarios.append(d)

        if not destinatarios:
            logger.warning(
                "[entregas:reporte] %d entregas en %s pero sin destinatarios "
                "activos; no se envía correo.",
                cantidad, fecha,
            )
            return {
                "ok": True,
                "fecha_objetivo": fecha.isoformat(),
                "cantidad": cantidad,
                "destinatarios": 0,
                "emails_enviados": 0,
                "errores": [],
                "skipped_reason": "sin_destinatarios",
            }

        # === 8) Enviar a cada destinatario (best-effort) ===
        enviados = 0
        errores = []
        for d in destinatarios:
            try:
                nombre = d.nombre or (d.email.split("@")[0] if d.email else "usuario")
                cuerpo_html_personalizado = cuerpo_html_full.replace(
                    "{{nombre_destinatario}}", nombre,
                )
                cuerpo_texto_personalizado = cuerpo_texto_full.replace(
                    "{{nombre_destinatario}}", nombre,
                )
                result = send_email(
                    to=d.email,
                    subject=asunto,
                    body=cuerpo_texto_personalizado,
                    html_body=cuerpo_html_personalizado,
                )
                if result.sent:
                    enviados += 1
                else:
                    errores.append(
                        f"{d.email}: {result.transport} ({result.detail or 'sin detalle'})"
                    )
            except Exception as exc:
                errores.append(f"{d.email}: excepcion {exc}")
                logger.exception(
                    "[entregas:reporte] Excepción enviando a %s: %s", d.email, exc,
                )

        # === 9) Marcar las entregas del día con reporte_enviado_en ===
        #     Solo si al menos UN envío fue exitoso. Si todo falló,
        #     dejamos NULL para reintentar mañana.
        ahora = datetime.utcnow()
        if enviados > 0:
            for e in entregas:
                e.reporte_enviado_en = ahora
            db.commit()

        # === 10) Auditoría global ===
        try:
            from app.services.auditoria_service import registrar_auditoria
            registrar_auditoria(
                db=db,
                ticket_id=None,
                usuario_id=None,
                accion="REPORTE_ENTREGAS_DIARIO",
                valor_anterior=None,
                valor_nuevo={
                    "fecha_objetivo": fecha.isoformat(),
                    "cantidad": cantidad,
                    "destinatarios": len(destinatarios),
                    "emails_enviados": enviados,
                    "errores": errores[:10],  # truncar para no inflar la auditoría
                },
                comentario=(
                    f"Reporte diario de entregas {fecha.isoformat()}: "
                    f"{enviados}/{len(destinatarios)} enviados, "
                    f"{cantidad} entregas."
                ),
                commit=True,
            )
        except Exception as exc:
            logger.debug(
                "[entregas:reporte] auditoría opcional: %s", exc,
            )

        logger.info(
            "[entregas:reporte] %s: %d entregas, %d/%d enviados, errores=%d",
            fecha, cantidad, enviados, len(destinatarios), len(errores),
        )
        return {
            "ok": True,
            "fecha_objetivo": fecha.isoformat(),
            "cantidad": cantidad,
            "destinatarios": len(destinatarios),
            "emails_enviados": enviados,
            "errores": errores,
            "skipped_reason": None,
        }
    except Exception as exc:
        logger.exception("[entregas:reporte] Error generando reporte: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            raise self.retry(exc=exc, countdown=300)
        except self.MaxRetriesExceededError:
            return {
                "ok": False,
                "fecha_objetivo": (
                    fecha_objetivo or datetime.utcnow().date().isoformat()
                ),
                "cantidad": 0,
                "destinatarios": 0,
                "emails_enviados": 0,
                "errores": [str(exc)],
                "skipped_reason": "max_retries_exceeded",
            }
    finally:
        db.close()


# ===========================================================================
#  Helpers de construcción del correo (privados)
# ===========================================================================
_ASUNTO_DEFAULT = "[Bitácora GRM] Entregas del día {{fecha}} ({{cantidad}})"

_PLANTILLA_HTML_DEFAULT = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Reporte diario de entregas</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;color:#0f172a;margin:0;padding:24px;background:#f8fafc;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
    <div style="background:#4f46e5;color:#ffffff;padding:20px 24px;">
      <h1 style="margin:0;font-size:18px;">Reporte diario de entregas</h1>
      <p style="margin:6px 0 0;font-size:13px;opacity:0.9;">{{fecha}}</p>
    </div>
    <div style="padding:24px;">
      <p style="margin:0 0 16px;font-size:14px;">
        Hola <strong>{{nombre_destinatario}}</strong>,
      </p>
      <p style="margin:0 0 20px;font-size:14px;line-height:1.6;">
        Se registraron <strong>{{cantidad}}</strong> entrega(s) en el día de hoy.
        El detalle se muestra a continuación:
      </p>
      {{tabla_html}}
      <p style="margin:24px 0 0;font-size:12px;color:#64748b;">
        Este reporte se generó automáticamente. Si un ticket fue reasignado
        o renombrado después de su entrega, este correo conserva los datos
        del momento de la transición.
      </p>
    </div>
  </div>
</body>
</html>
"""

_PLANTILLA_TEXTO_DEFAULT = """Reporte diario de entregas - {{fecha}}

Hola {{nombre_destinatario}},

Se registraron {{cantidad}} entrega(s) en el día de hoy:

{{tabla_texto}}

--
Este reporte se generó automáticamente.
"""

_FIRMA_DEFAULT = """<p style="margin:24px 0 0;color:#64748b;font-size:12px;">
  --<br>
  <strong>Equipo Bitácora GRM</strong><br>
  Reporte automático generado al final del día.
</p>"""


def _format_fecha_larga(fecha: date) -> str:
    """Devuelve la fecha en formato legible en español."""
    dias = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    try:
        wd = dias[fecha.weekday()]
        mes = meses[fecha.month - 1]
        return f"{wd} {fecha.day} de {mes} de {fecha.year}"
    except Exception:
        return fecha.isoformat()


def _render_tabla_html(entregas, base_url: str = "") -> str:
    """Renderiza la tabla HTML con los tickets del día."""
    if not entregas:
        return "<p style='color:#64748b'>Sin entregas registradas.</p>"
    base = (base_url or "").rstrip("/")
    rows = []
    for e in entregas:
        codigo = _e(e.ticket_codigo) or "(sin código)"
        titulo = _e(e.ticket_titulo) or "(sin título)"
        estado = _e(e.estado_destino_nombre) or ""
        asignado = _e(e.asignado_nombre) or "—"
        hora = e.fecha_entrega.strftime("%H:%M") if e.fecha_entrega else ""
        url = f"{base}/tickets#{e.ticket_id}" if (base and e.ticket_id) else ""
        link_html = (
            f'<a href="{_e(url)}" style="color:#4f46e5;text-decoration:none;">'
            f"{_e(codigo)}</a>" if url else f"<strong>{_e(codigo)}</strong>"
        )
        rows.append(
            "<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;font-family:monospace'>{link_html}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0'>{_e(titulo)}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0'>{_e(estado)}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0'>{_e(asignado)}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#64748b'>{_e(hora)}</td>"
            "</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        "<thead><tr style='background:#f1f5f9;text-align:left;'>"
        "<th style='padding:8px 12px'>Código</th>"
        "<th style='padding:8px 12px'>Título</th>"
        "<th style='padding:8px 12px'>Estado</th>"
        "<th style='padding:8px 12px'>Asignado</th>"
        "<th style='padding:8px 12px'>Hora</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _render_tabla_texto(entregas) -> str:
    """Renderiza la versión en texto plano de la lista de entregas."""
    if not entregas:
        return "Sin entregas registradas."
    lines = []
    for e in entregas:
        codigo = (e.ticket_codigo or "").strip() or "(sin código)"
        titulo = (e.ticket_titulo or "").strip() or "(sin título)"
        estado = (e.estado_destino_nombre or "").strip()
        asignado = (e.asignado_nombre or "").strip() or "—"
        hora = e.fecha_entrega.strftime("%H:%M") if e.fecha_entrega else ""
        lines.append(
            f"  - [{codigo}] {titulo}\n"
            f"      Estado: {estado}  ·  Asignado: {asignado}  ·  Hora: {hora}"
        )
    return "\n".join(lines)


def _e(s) -> str:
    """Escape HTML básico."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )