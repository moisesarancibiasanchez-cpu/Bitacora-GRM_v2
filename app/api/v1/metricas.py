"""
Endpoints de métricas y dashboard.
Sprint 1 - Feature Trello premium: Dashboard con KPIs.
"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket, Prioridad
from app.models.estado import Estado
from app.models.usuario import Usuario
from app.models.auditoria import Auditoria
from app.models.comentario import Comentario
from app.models.etiqueta import Etiqueta, ticket_etiquetas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metricas", tags=["Métricas"])


@router.get("/resumen")
def resumen_dashboard(
    dias: int = 30,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Resumen agregado de métricas para el dashboard.

    - total_tickets, abiertos, cerrados, archivados
    - distribucion_por_estado, por_prioridad
    - tickets_por_dia (para grafico de actividad)
    - tiempo_promedio_resolucion (horas)
    - sla_cumplido_pct
    - top_etiquetas
    - top_agentes
    """
    # === Conteos básicos ===
    total = db.query(func.count(Ticket.id)).scalar() or 0
    archivados = db.query(func.count(Ticket.id)).filter(Ticket.archivado == True).scalar() or 0  # noqa: E712
    activos = total - archivados

    # === Distribución por estado ===
    estados_count = (
        db.query(Estado.nombre, Estado.color, func.count(Ticket.id))
        .outerjoin(Ticket, Ticket.estado_id == Estado.id)
        .group_by(Estado.id, Estado.nombre, Estado.color, Estado.orden)
        .order_by(Estado.orden)
        .all()
    )
    distribucion_estado = [
        {"nombre": nombre, "color": color, "total": cnt}
        for nombre, color, cnt in estados_count
    ]

    # === Distribución por prioridad ===
    prioridades_count = (
        db.query(Ticket.prioridad, func.count(Ticket.id))
        .filter(Ticket.archivado == False)  # noqa: E712
        .group_by(Ticket.prioridad)
        .all()
    )
    distribucion_prioridad = [
        {"prioridad": p.value if p else "sin_prioridad", "total": cnt}
        for p, cnt in prioridades_count
    ]

    # === Tickets creados por día (últimos N días) ===
    fecha_limite = datetime.utcnow() - timedelta(days=dias)
    tickets_por_dia = (
        db.query(
            func.date(Ticket.created_at).label("fecha"),
            func.count(Ticket.id).label("total"),
        )
        .filter(Ticket.created_at >= fecha_limite)
        .group_by(func.date(Ticket.created_at))
        .order_by(func.date(Ticket.created_at))
        .all()
    )
    serie_actividad = [
        {"fecha": str(fecha), "total": total}
        for fecha, total in tickets_por_dia
    ]

    # === SLA cumplimiento ===
    sla_si = db.query(func.count(Ticket.id)).filter(Ticket.sla_cumplido == 1).scalar() or 0
    sla_no = db.query(func.count(Ticket.id)).filter(Ticket.sla_cumplido == 0).scalar() or 0
    sla_pendiente = db.query(func.count(Ticket.id)).filter(
        Ticket.sla_cumplido == -1, Ticket.fecha_vencimiento_sla.isnot(None)
    ).scalar() or 0
    sla_total = sla_si + sla_no
    sla_pct = (sla_si / sla_total * 100) if sla_total > 0 else 0

    # === Top etiquetas ===
    top_etiquetas = (
        db.query(Etiqueta.nombre, Etiqueta.color, func.count(ticket_etiquetas.c.ticket_id).label("total"))
        .join(ticket_etiquetas, ticket_etiquetas.c.etiqueta_id == Etiqueta.id)
        .group_by(Etiqueta.id, Etiqueta.nombre, Etiqueta.color)
        .order_by(func.count(ticket_etiquetas.c.ticket_id).desc())
        .limit(5)
        .all()
    )
    top_etiquetas_list = [
        {"nombre": n, "color": c, "total": t} for n, c, t in top_etiquetas
    ]

    # === Top agentes (asignados) ===
    top_agentes = (
        db.query(Usuario.nombre_completo, func.count(Ticket.id).label("total"))
        .join(Ticket, Ticket.asignado_id == Usuario.id)
        .filter(Ticket.archivado == False)  # noqa: E712
        .group_by(Usuario.id, Usuario.nombre_completo)
        .order_by(func.count(Ticket.id).desc())
        .limit(5)
        .all()
    )
    top_agentes_list = [
        {"nombre": n, "total": t} for n, t in top_agentes
    ]

    # === Tickets críticos sin asignar ===
    criticos_sin_asignar = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.prioridad == Prioridad.CRITICA,
            Ticket.asignado_id.is_(None),
            Ticket.archivado == False,  # noqa: E712
        )
        .scalar()
    ) or 0

    return {
        "periodo_dias": dias,
        "totales": {
            "total": total,
            "activos": activos,
            "archivados": archivados,
            "criticos_sin_asignar": criticos_sin_asignar,
        },
        "sla": {
            "cumplidos": sla_si,
            "incumplidos": sla_no,
            "pendientes": sla_pendiente,
            "porcentaje_cumplimiento": round(sla_pct, 1),
        },
        "distribucion_estado": distribucion_estado,
        "distribucion_prioridad": distribucion_prioridad,
        "actividad_por_dia": serie_actividad,
        "top_etiquetas": top_etiquetas_list,
        "top_agentes": top_agentes_list,
    }
