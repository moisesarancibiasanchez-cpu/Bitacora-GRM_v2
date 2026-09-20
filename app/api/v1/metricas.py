"""
Endpoints de métricas y dashboard.
Sprint 1 - Feature Trello premium: Dashboard con KPIs.
Sprint 2 - Mejoras: filtros por tipo Incidencia, Cuenta de Resultado, riesgo SLA, top agentes con stats.
"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func, case, and_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
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

    # === Conteos específicos por tipo Incidencia (Sprint 2) ===
    # total: incluye todos los tipos de tickets
    # incidencias: solo tipo Incidencia
    incidencias_total = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.tipo == TipoIncidencia.INCIDENCIA)
        .scalar() or 0
    )
    incidencias_activas = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.tipo == TipoIncidencia.INCIDENCIA,
            Ticket.archivado == False,  # noqa: E712
        )
        .scalar() or 0
    )
    # Nuevas incidencias en los últimos 7 días
    hace_7d = datetime.utcnow() - timedelta(days=7)
    nuevas_7d = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.created_at >= hace_7d)
        .scalar() or 0
    )
    incidencias_nuevas_7d = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.tipo == TipoIncidencia.INCIDENCIA,
            Ticket.created_at >= hace_7d,
        )
        .scalar() or 0
    )
    # Backlog: incidencias activas creadas hace más de 7 días
    backlog_7d = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.tipo == TipoIncidencia.INCIDENCIA,
            Ticket.archivado == False,  # noqa: E712
            Ticket.created_at < hace_7d,
        )
        .scalar() or 0
    )

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
        # === Conteos Sprint 2 (no rompen consumidores existentes) ===
        "incidencias": {
            "total": incidencias_total,
            "activas": incidencias_activas,
            "nuevas_7d": incidencias_nuevas_7d,
            "backlog_7d": backlog_7d,
        },
        "nuevas_7d": nuevas_7d,
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


@router.get("/dashboard-completo")
def dashboard_completo(
    dias: int = 30,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Endpoint extendido para el dashboard rediseñado (Sprint 2).

    Devuelve todos los datos que consume el dashboard nuevo:
    - totales, incidencias, sla (igual que /resumen)
    - distribuciones por estado y prioridad
    - serie de actividad por día (para sparklines y chart)
    - funnel de avance por estado
    - próximos a vencer SLA (lista de tickets)
    - cuenta de resultado (pivot módulo × resultado de pruebas)
    - top agentes enriquecido (asignados, abiertas, cerradas)
    """
    # Reutilizamos la lógica del resumen para evitar duplicación
    resumen = resumen_dashboard(dias=dias, db=db, usuario=usuario)

    # === Funnel: total por estado (orden estable por orden del estado) ===
    funnel_rows = (
        db.query(Estado.nombre, Estado.color, Estado.es_final, func.count(Ticket.id))
        .outerjoin(Ticket, and_(Ticket.estado_id == Estado.id, Ticket.archivado == False))  # noqa: E712
        .group_by(Estado.id, Estado.nombre, Estado.color, Estado.es_final, Estado.orden)
        .order_by(Estado.orden)
        .all()
    )
    funnel = [
        {"estado": n, "color": c, "total": cnt}
        for n, c, _es_final, cnt in funnel_rows
    ]

    # === Próximos a vencer SLA (default 72h) ===
    ahora = datetime.utcnow()
    hasta_72h = ahora + timedelta(hours=72)
    riesgo_rows = (
        db.query(Ticket, Estado.color.label("estado_color"))
        .join(Estado, Estado.id == Ticket.estado_id)
        .filter(
            Ticket.tipo == TipoIncidencia.INCIDENCIA,
            Ticket.archivado == False,  # noqa: E712
            Ticket.fecha_vencimiento_sla.isnot(None),
            Ticket.fecha_vencimiento_sla <= hasta_72h,
            Ticket.sla_cumplido != 1,
        )
        .order_by(Ticket.fecha_vencimiento_sla.asc())
        .limit(20)
        .all()
    )
    riesgo = []
    for t, estado_color in riesgo_rows:
        horas = (t.fecha_vencimiento_sla - ahora).total_seconds() / 3600.0
        riesgo.append({
            "id": t.id,
            "codigo": t.codigo,
            "titulo": t.titulo,
            "prioridad": t.prioridad.value if t.prioridad else "media",
            "estado": t.estado.nombre if t.estado else "",
            "estado_color": estado_color or "#94a3b8",
            "asignado": t.asignado.nombre_completo if t.asignado else None,
            "horas_restantes": round(horas, 1),
        })

    # === Cuenta de Resultado: pivot módulo × resultado de pruebas (sólo incidencias cerradas) ===
    # Filtramos tickets con fecha_completado (i.e., cerrados/resueltos)
    cuenta_rows = (
        db.query(
            Ticket.modulo,
            Ticket.resultado_pruebas,
            func.count(Ticket.id).label("total"),
        )
        .filter(
            Ticket.tipo == TipoIncidencia.INCIDENCIA,
            Ticket.fecha_completado.isnot(None),
            Ticket.resultado_pruebas.isnot(None),
            Ticket.archivado == False,  # noqa: E712
        )
        .group_by(Ticket.modulo, Ticket.resultado_pruebas)
        .all()
    )

    # Mapeo de módulo → dict con conteo por resultado
    cuenta_dict = {}
    for modulo, resultado, total in cuenta_rows:
        mod_key = modulo or "(sin módulo)"
        if mod_key not in cuenta_dict:
            cuenta_dict[mod_key] = {"modulo": mod_key, "total": 0}
        cuenta_dict[mod_key]["total"] += total
        cuenta_dict[mod_key][resultado] = cuenta_dict[mod_key].get(resultado, 0) + total

    cuenta_resultado = sorted(
        cuenta_dict.values(), key=lambda x: x["total"], reverse=True
    )

    # === Top agentes enriquecido (asignados, abiertas, cerradas en el periodo) ===
    fecha_limite = ahora - timedelta(days=dias)
    top_agentes_rows = (
        db.query(
            Usuario.id,
            Usuario.nombre_completo,
            func.count(Ticket.id).filter(
                Ticket.archivado == False  # noqa: E712
            ).label("abiertas"),
            func.count(Ticket.id).filter(
                Ticket.archivado == False,  # noqa: E712
                Ticket.fecha_completado.isnot(None),
                Ticket.fecha_completado >= fecha_limite,
            ).label("cerradas_periodo"),
            func.count(Ticket.id).label("total_asignados"),
        )
        .join(Ticket, Ticket.asignado_id == Usuario.id)
        .filter(Usuario.is_active == True)  # noqa: E712
        .group_by(Usuario.id, Usuario.nombre_completo)
        .order_by(func.count(Ticket.id).desc())
        .limit(5)
        .all()
    )
    top_agentes = [
        {
            "id": uid,
            "nombre": nombre,
            "abiertas": abiertas or 0,
            "cerradas": cerradas_periodo or 0,
            "total": total_asignados or 0,
        }
        for uid, nombre, abiertas, cerradas_periodo, total_asignados in top_agentes_rows
    ]

    # === Series de actividad por día (con split levantadas/cerradas) ===
    serie_actividad = []
    for i in range(dias - 1, -1, -1):
        d_ini = ahora - timedelta(days=i)
        d_ini = d_ini.replace(hour=0, minute=0, second=0, microsecond=0)
        d_fin = d_ini.replace(hour=23, minute=59, second=59, microsecond=999000)

        levantadas = (
            db.query(func.count(Ticket.id))
            .filter(Ticket.created_at >= d_ini, Ticket.created_at <= d_fin)
            .scalar() or 0
        )
        cerradas = (
            db.query(func.count(Ticket.id))
            .filter(
                Ticket.fecha_completado.isnot(None),
                Ticket.fecha_completado >= d_ini,
                Ticket.fecha_completado <= d_fin,
            )
            .scalar() or 0
        )
        serie_actividad.append({
            "fecha": d_ini.strftime("%Y-%m-%d"),
            "levantadas": levantadas,
            "cerradas": cerradas,
        })

    # === Distribución por estado / prioridad (alias para el dashboard nuevo) ===
    dist_estado = resumen["distribucion_estado"]
    dist_prioridad = resumen["distribucion_prioridad"]

    # === Series para sparklines (sintéticas desde la serie de actividad) ===
    spark_levantadas = [s["levantadas"] for s in serie_actividad]
    spark_incidencias = [
        (
            db.query(func.count(Ticket.id))
            .filter(
                Ticket.tipo == TipoIncidencia.INCIDENCIA,
                Ticket.created_at >= (
                    ahora - timedelta(days=i)
                ).replace(hour=0, minute=0, second=0, microsecond=0),
                Ticket.created_at <= (
                    ahora - timedelta(days=i)
                ).replace(hour=23, minute=59, second=59, microsecond=999000),
            ).scalar() or 0
        )
        for i in range(dias - 1, -1, -1)
    ]
    # SLA sparkline: porcentaje de cumplimiento sobre tickets cerrados en cada día (suavizado)
    spark_sla = []
    spark_backlog = []
    for i in range(dias - 1, -1, -1):
        d_fin = (ahora - timedelta(days=i)).replace(hour=23, minute=59, second=59, microsecond=999000)
        cerrados_hasta = (
            db.query(func.count(Ticket.id))
            .filter(
                Ticket.fecha_completado.isnot(None),
                Ticket.fecha_completado <= d_fin,
                Ticket.sla_cumplido.in_([0, 1]),
            ).scalar() or 0
        )
        sla_ok = (
            db.query(func.count(Ticket.id))
            .filter(
                Ticket.fecha_completado.isnot(None),
                Ticket.fecha_completado <= d_fin,
                Ticket.sla_cumplido == 1,
            ).scalar() or 0
        )
        sla_pct_dia = (sla_ok / cerrados_hasta * 100) if cerrados_hasta > 0 else 0
        spark_sla.append(round(sla_pct_dia, 1))
        backlog_dia = (
            db.query(func.count(Ticket.id))
            .filter(
                Ticket.tipo == TipoIncidencia.INCIDENCIA,
                Ticket.archivado == False,  # noqa: E712
                Ticket.created_at <= d_fin,
                Ticket.fecha_completado.is_(None),
            ).scalar() or 0
        )
        spark_backlog.append(backlog_dia)

    return {
        "periodo_dias": dias,
        "timestamp": ahora.isoformat(),
        "totales": resumen["totales"],
        "incidencias": resumen["incidencias"],
        "nuevas_7d": resumen["nuevas_7d"],
        "sla": resumen["sla"],
        "distribucion_estado": dist_estado,
        "distribucion_prioridad": dist_prioridad,
        "actividad_por_dia": serie_actividad,
        "funnel": funnel,
        "riesgo_sla": riesgo,
        "cuenta_resultado": cuenta_resultado,
        "top_agentes": top_agentes,
        "top_etiquetas": resumen["top_etiquetas"],
        # Series listas para sparklines
        "sparklines": {
            "levantadas": spark_levantadas,
            "incidencias": spark_incidencias,
            "sla": spark_sla,
            "backlog": spark_backlog,
        },
    }
