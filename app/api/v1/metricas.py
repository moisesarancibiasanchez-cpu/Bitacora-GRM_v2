"""
Endpoints de métricas y dashboard.
Sprint 1 - Feature Trello premium: Dashboard con KPIs.
"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket, Prioridad
from app.models.estado import Estado
from app.models.usuario import Usuario
from app.models.auditoria import Auditoria
from app.models.comentario import Comentario
from app.models.etiqueta import Etiqueta, ticket_etiquetas
from app.models.automacion import ReglaAutomatizacion

# Columnas esperadas para la tabla pivote "Cuenta de Resultado"
# Réplica del rango A64:H81 de la hoja REPORTE del Excel UAT.
_RESULTADOS_PIVOTE = (
    "N/A",
    "NOK",
    "OK",
    "OK CON OBS.",
    "POSTERGADA",
    "",  # (en blanco) — sin resultado
)

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

    # === Tickets sin asignar (NO críticos) ===
    # Se mantiene `criticos_sin_asignar` por compatibilidad con consumidores
    # previos; este nuevo campo alimenta el KPI "Sin asignar" del dashboard
    # y se reporta como COMPLEMENTO del KPI "Críticos sin asignar" que ya
    # existe en el grid principal: aquí se cuentan sólo los tickets sin
    # asignar cuya prioridad NO es CRITICA (los críticos van a su propio KPI
    # para evitar doble conteo en la barra compacta).
    sin_asignar = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.asignado_id.is_(None),
            Ticket.prioridad != Prioridad.CRITICA,
            Ticket.archivado == False,  # noqa: E712
        )
        .scalar()
    ) or 0

    # === Tickets "Abiertos" (no en estado final) ===
    # `activos` arriba (total - archivados) sigue intacto por compatibilidad.
    # Este NUEVO campo alimenta el KPI "Abiertos" del dashboard: cuenta
    # tickets cuyo estado NO está marcado como `es_final=True` y que
    # tampoco están archivados (semánticamente: tickets en curso de trabajo).
    subq_estados_finales = (
        db.query(Estado.id).filter(Estado.es_final == True).subquery()  # noqa: E712
    )
    abiertos = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.estado_id.notin_(subq_estados_finales),
            Ticket.archivado == False,  # noqa: E712
        )
        .scalar()
    ) or 0

    # === Reglas Butler activas (automatizaciones) ===
    reglas_activas = (
        db.query(func.count(ReglaAutomatizacion.id))
        .filter(ReglaAutomatizacion.activo == True)  # noqa: E712
        .scalar()
    ) or 0

    return {
        "periodo_dias": dias,
        "totales": {
            "total": total,
            "activos": activos,
            "archivados": archivados,
            "criticos_sin_asignar": criticos_sin_asignar,
            "sin_asignar": sin_asignar,
            "abiertos": abiertos,
            "reglas_activas": reglas_activas,
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


@router.get("/cuenta-resultado")
def cuenta_resultado(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Tabla pivote "Cuenta de Resultado" — réplica del rango A64:H81 del Excel.

    Devuelve el conteo de tickets agrupados por módulo y resultado_pruebas
    filtrado por ``ambiente`` (default ``QA``). La respuesta se serializa
    con la forma exacta esperada por el componente del dashboard:

      {
        "ambiente": "QA",
        "columnas": ["N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "(en blanco)"],
        "filas": [
          {"modulo": "Auditoría", "valores": {"N/A": 1, "NOK": 0, ...}, "total": 9},
          ...
          {"modulo": "(en blanco)", "valores": {...}, "total": 0},
        ],
        "totales_por_columna": {"N/A": 130, "NOK": 10, "OK": 635, ...},
        "total_general": 877
      }

    Notas:
      - ``(en blanco)`` como columna cuenta tickets con ``resultado_pruebas``
        ``NULL`` o cadena vacía.
      - ``(en blanco)`` como fila cuenta tickets con ``modulo`` ``NULL`` o
        cadena vacía.
      - El parámetro ``ambiente`` acepta ``QA`` o ``PRODUCCION``.
    """
    ambiente_filtro = "QA"

    # Columnas dinámicas: usamos la misma definición que el front (incluye
    # la columna "(en blanco)" que agrupa NULL/vacío en resultado_pruebas).
    columnas_front = [
        "N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "(en blanco)",
    ]

    # Mapeo: nombre en front → valor literal en tickets.resultado_pruebas
    # La columna "(en blanco)" se calcula como "IS NULL OR = ''".
    sql_columnas = [
        ("N/A",          Ticket.resultado_pruebas == "N/A"),
        ("NOK",          Ticket.resultado_pruebas == "NOK"),
        ("OK",           Ticket.resultado_pruebas == "OK"),
        ("OK CON OBS.",  Ticket.resultado_pruebas == "OK CON OBS."),
        ("POSTERGADA",   Ticket.resultado_pruebas == "POSTERGADA"),
        ("(en blanco)",  Ticket.resultado_pruebas.is_(None) | (Ticket.resultado_pruebas == "")),
    ]

    # Construir agregación con CASE WHEN por columna (una sola pasada SQL).
    sums = []
    for nombre, cond in sql_columnas:
        # `case((cond, 1), else_=0)` produce un entero 0/1 que se suma.
        sums.append(
            func.coalesce(
                func.sum(case((cond, 1), else_=0)),
                0,
            ).label(nombre)
        )

    rows = (
        db.query(
            Ticket.modulo.label("modulo"),
            *sums,
            func.count(Ticket.id).label("total"),
        )
        .filter(Ticket.ambiente == ambiente_filtro)
        .group_by(Ticket.modulo)
        .order_by(Ticket.modulo.asc())
        .all()
    )

    # Normalizar filas: módulo NULL o vacío → "(en blanco)".
    filas = []
    totales_por_columna = {c: 0 for c in columnas_front}
    total_general = 0

    for r in rows:
        modulo = r.modulo if (r.modulo and r.modulo.strip()) else "(en blanco)"
        valores = {}
        fila_total = 0
        for nombre_col, _ in sql_columnas:
            v = int(getattr(r, nombre_col, 0) or 0)
            valores[nombre_col] = v
            totales_por_columna[nombre_col] += v
            fila_total += v
        filas.append({
            "modulo": modulo,
            "valores": valores,
            "total": fila_total,
        })
        total_general += fila_total

    # Ordenar filas con "(en blanco)" al final para coincidir con el Excel.
    filas_ordenadas = sorted(
        filas,
        key=lambda f: (f["modulo"] == "(en blanco)", f["modulo"]),
    )

    # Asegurar que el modulo "(en blanco)" exista aunque no haya tickets.
    if not any(f["modulo"] == "(en blanco)" for f in filas_ordenadas):
        filas_ordenadas.append({
            "modulo": "(en blanco)",
            "valores": {c: 0 for c in columnas_front},
            "total": 0,
        })

    return {
        "ambiente": ambiente_filtro,
        "columnas": columnas_front,
        "filas": filas_ordenadas,
        "totales_por_columna": totales_por_columna,
        "total_general": total_general,
        # Metadatos para tooltips / trazabilidad.
        "fuente": "tickets",
        "filtro_ambiente_default": "QA",
        "nota_postergada": (
            "POSTERGADA es la normalización del valor original "
            "'POSTERGADA A GARANTÍA' en la migración UAT."
        ),
    }
