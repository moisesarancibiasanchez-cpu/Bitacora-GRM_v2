"""
Endpoints de métricas y dashboard.
Sprint 1 - Feature Trello premium: Dashboard con KPIs.
Sprint 2 - Mejoras: filtros por tipo Incidencia, Cuenta de Resultado, riesgo SLA, top agentes con stats.
Sprint 2 (restaurado) - Endpoint dedicado /cuenta-resultado con pivot módulo ×
resultado_pruebas (réplica del rango A64:H81 de la hoja REPORTE del Excel UAT)
+ drill-down por celda, exportación CSV y filtrado por ambiente (QA/PRODUCCION).
"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.models.estado import Estado
from app.models.usuario import Usuario
from app.models.auditoria import Auditoria
from app.models.comentario import Comentario
from app.models.etiqueta import Etiqueta, ticket_etiquetas

# Columnas esperadas para la tabla pivote "Cuenta de Resultado"
# Réplica del rango A64:H81 de la hoja REPORTE del Excel UAT.
#
# NOTA: Incluye TODOS los valores del LOV de ``resultado_pruebas``
# (N/A, NOK, OK, OK CON OBS., POSTERGADA, DESESTIMADA) más la
# categoría derivada "(en blanco)" para valores NULL/vacíos. Si
# el LOV crece en el futuro, basta con agregar el nuevo valor aquí
# y darlo de alta en ``sql_columnas`` más abajo para que el pivot
# lo refleje sin perder tickets.
_RESULTADOS_PIVOTE = (
    "N/A",
    "NOK",
    "OK",
    "OK CON OBS.",
    "POSTERGADA",
    "DESESTIMADA",
    "",  # (en blanco) — sin resultado
)

# Normalización de etiquetas de módulo para la tabla pivote.
# Mapea variantes conocidas (ej: heredadas de la migración UAT) a
# su forma canónica. Si en el futuro aparecen nuevas variantes, se
# agregan aquí para que el pivot muestre una fila única y consistente.
MODULO_ALIAS = {
    "Registro Información": "Registro de Información",
}


def _normalizar_modulo(modulo: str) -> str:
    """Devuelve la etiqueta canónica del módulo para mostrar en el pivot."""
    if not modulo or not modulo.strip():
        return "(en blanco)"
    return MODULO_ALIAS.get(modulo, modulo)


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


# =============================================================================
# Cuenta de Resultado — endpoint dedicado (restaurado).
#
# Réplica del rango A64:H81 de la hoja REPORTE del Excel UAT.
#   - Pivot módulo (filas) × resultado_pruebas (columnas).
#   - Filtro por ``ambiente`` (default QA).
#   - Acepta TODAS las variantes del LOV (incluye mayúsculas mixtas, con/sin
#     punto final, plurales y nombres legacy de la migración UAT) para no
#     perder tickets por nomenclatura heredada.
#   - Incluye la columna derivada "(en blanco)" que agrupa NULL/vacíos.
#   - Drill-down por celda vía /cuenta-resultado/detalle (HTMX → modal).
# =============================================================================


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
        "columnas": ["N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA", "(en blanco)"],
        "filas": [
          {"modulo": "Auditoría", "valores": {"N/A": 1, "NOK": 0, ...}, "total": 9},
          ...
        ],
        "totales_por_columna": {"N/A": 130, "NOK": 10, "OK": 635, ...},
        "total_general": 877
      }
    """
    ambiente_filtro = "QA"

    # Columnas dinámicas: mismas que el front (incluye "(en blanco)" para
    # agrupar NULL/vacíos en resultado_pruebas). DESESTIMADA se incluye
    # explícitamente para que esos tickets NO queden excluidos del pivot.
    columnas_front = [
        "N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA",
        "(en blanco)",
    ]

    def _eq_ci(*literales):
        """SQL case-insensitive y tolerante a espacios."""
        norm = func.upper(func.trim(Ticket.resultado_pruebas))
        return or_(*[norm == lit.upper() for lit in literales])

    sql_columnas = [
        ("N/A",         _eq_ci("N/A")),
        ("NOK",         _eq_ci("NOK")),
        ("OK",          _eq_ci("OK")),
        ("OK CON OBS.", _eq_ci(
            "OK CON OBS.", "OK CON OBS", "OK CON OBSERVACIONES",
            "OK CON OBSERVACIÓN", "OK CON OBSERVACION",
            "OK CON OBSERV.", "OK C/OBS", "OK COBS",
        )),
        ("POSTERGADA",  _eq_ci(
            "POSTERGADA", "POSTERGADA A GARANTÍA",
            "POSTERGADA A GARANTIA", "POSTERGADO",
        )),
        ("DESESTIMADA", _eq_ci("DESESTIMADA", "DESESTIMADO")),
        ("(en blanco)", Ticket.resultado_pruebas.is_(None) | (func.trim(Ticket.resultado_pruebas) == "")),
    ]

    sums = []
    for nombre, cond in sql_columnas:
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

    filas = {}
    totales_por_columna = {c: 0 for c in columnas_front}
    total_general = 0

    for r in rows:
        modulo_canonico = _normalizar_modulo(r.modulo)
        valores = {}
        fila_total = 0
        for nombre_col, _ in sql_columnas:
            v = int(getattr(r, nombre_col, 0) or 0)
            valores[nombre_col] = v
            fila_total += v
        if modulo_canonico in filas:
            existente = filas[modulo_canonico]
            for col, v in valores.items():
                existente["valores"][col] = existente["valores"].get(col, 0) + v
            existente["total"] += fila_total
        else:
            filas[modulo_canonico] = {
                "modulo": modulo_canonico,
                "valores": valores,
                "total": fila_total,
            }
        for col, v in valores.items():
            totales_por_columna[col] += v
        total_general += fila_total

    filas_ordenadas = sorted(
        filas.values(),
        key=lambda f: (f["modulo"] == "(en blanco)", f["modulo"]),
    )

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
        "fuente": "tickets",
        "filtro_ambiente_default": "QA",
        "nota_postergada": (
            "POSTERGADA es la normalización del valor original "
            "'POSTERGADA A GARANTÍA' en la migración UAT."
        ),
    }


# Mapa de colores para el badge del modal (sincronizado con el front).
CUENTA_RESULTADO_COLORES_PARA_MODAL = {
    "N/A":         {"bg": "#94a3b8", "text": "#ffffff"},
    "NOK":         {"bg": "#dc2626", "text": "#ffffff"},
    "OK":          {"bg": "#16a34a", "text": "#ffffff"},
    "OK CON OBS.": {"bg": "#eab308", "text": "#1f2937"},
    "POSTERGADA":  {"bg": "#ea580c", "text": "#ffffff"},
    "DESESTIMADA": {"bg": "#7c3aed", "text": "#ffffff"},
    "(en blanco)": {"bg": "#cbd5e1", "text": "#475569"},
}


@router.get("/cuenta-resultado/detalle")
def cuenta_resultado_detalle(
    modulo: str,
    resultado: str,
    ambiente: str = "QA",
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Drill-down: HTML con el detalle de tickets de una celda del pivot.

    Consumido por HTMX al hacer clic en cualquier celda numérica de la tabla
    "Cuenta de Resultado". Devuelve el modal con la lista de tickets que
    componen el valor agregado de la celda, con filtros módulo/resultado/
    ambiente preservados.
    """
    from fastapi.responses import HTMLResponse

    modulo_filtro = (modulo or "").strip()
    resultado_filtro = (resultado or "").strip()
    ambiente_filtro = (ambiente or "QA").strip().upper()
    if ambiente_filtro not in ("QA", "PRODUCCION"):
        ambiente_filtro = "QA"

    # === Filtro de MÓDULO ===
    if modulo_filtro == "(en blanco)":
        modulo_cond = Ticket.modulo.is_(None) | (func.trim(Ticket.modulo) == "")
    else:
        variantes = [modulo_filtro]
        for alias, canonico in MODULO_ALIAS.items():
            if canonico == modulo_filtro:
                variantes.append(alias)
        for alias, canonico in MODULO_ALIAS.items():
            if alias == modulo_filtro:
                variantes.append(canonico)
        modulo_cond = or_(*[
            func.upper(func.trim(Ticket.modulo)) == v.upper()
            for v in variantes
        ])

    # === Filtro de RESULTADO PRUEBAS ===
    resultado_norm = func.upper(func.trim(Ticket.resultado_pruebas))

    if resultado_filtro == "(en blanco)":
        resultado_cond = (
            Ticket.resultado_pruebas.is_(None)
            | (func.trim(Ticket.resultado_pruebas) == "")
        )
    elif resultado_filtro.upper() == "N/A":
        resultado_cond = resultado_norm == "N/A"
    elif resultado_filtro.upper() == "NOK":
        resultado_cond = resultado_norm == "NOK"
    elif resultado_filtro.upper() == "OK":
        resultado_cond = resultado_norm == "OK"
    elif resultado_filtro.upper() in ("OK CON OBS.", "OK CON OBS"):
        resultado_cond = resultado_norm.in_([
            "OK CON OBS.", "OK CON OBS", "OK CON OBSERVACIONES",
            "OK CON OBSERVACIÓN", "OK CON OBSERVACION",
            "OK CON OBSERV.", "OK C/OBS", "OK COBS",
        ])
    elif resultado_filtro.upper() == "POSTERGADA":
        resultado_cond = resultado_norm.in_([
            "POSTERGADA", "POSTERGADA A GARANTÍA",
            "POSTERGADA A GARANTIA", "POSTERGADO",
        ])
    elif resultado_filtro.upper() == "DESESTIMADA":
        resultado_cond = resultado_norm.in_(["DESESTIMADA", "DESESTIMADO"])
    else:
        resultado_cond = func.upper(func.trim(Ticket.resultado_pruebas)) == resultado_filtro.upper()

    tickets_q = (
        db.query(Ticket, Estado, Usuario)
        .outerjoin(Estado, Ticket.estado_id == Estado.id)
        .outerjoin(Usuario, Ticket.asignado_id == Usuario.id)
        .filter(Ticket.ambiente == ambiente_filtro)
        .filter(modulo_cond)
        .filter(resultado_cond)
        .order_by(Ticket.codigo.asc())
        .all()
    )

    def _color_prioridad(p):
        return {
            "critica": ("bg-red-100 text-red-700", "CRÍTICA"),
            "alta":    ("bg-orange-100 text-orange-700", "ALTA"),
            "media":   ("bg-yellow-100 text-yellow-700", "MEDIA"),
            "baja":    ("bg-slate-100 text-slate-600", "BAJA"),
        }.get(getattr(p, "value", "") or "", ("bg-slate-100 text-slate-600", "—"))

    def _fmt_fecha(dt):
        if not dt:
            return '<span class="text-slate-400">—</span>'
        try:
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return str(dt)

    def _fmt_resultado(val):
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return '<span class="text-slate-400 italic">(en blanco)</span>'
        return val

    def _fmt_item(val):
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return '<span class="text-slate-400">—</span>'
        return val

    rows_html = []
    for t, estado, asignado in tickets_q:
        prio_cls, prio_label = _color_prioridad(t.prioridad)
        estado_nombre = estado.nombre if estado else "—"
        estado_color = estado.color if (estado and estado.color) else "#94a3b8"
        asignado_nombre = asignado.nombre_completo if asignado else "—"
        ticket_id = getattr(t, "id", None)
        if ticket_id is not None:
            accion_html = (
                "<td class='px-3 py-2 text-center whitespace-nowrap'>"
                f"<button type='button' "
                f"data-ticket-id='{ticket_id}' "
                f"data-drill-cr-row='1' "
                f"hx-get='/api/v1/tickets/{ticket_id}/detalle-html?tab=detalles' "
                f"hx-target='#modal-cuenta-resultado-root' "
                f"hx-swap='innerHTML' "
                f"title='Ver y editar ticket {t.codigo or ticket_id}' "
                f"class='inline-flex items-center justify-center w-7 h-7 rounded-md text-indigo-600 hover:bg-indigo-50 hover:text-indigo-800 transition'>"
                "<svg class='w-4 h-4' fill='none' stroke='currentColor' viewBox='0 0 24 24'>"
                "<path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M15 12a3 3 0 11-6 0 3 3 0 016 0z'/>"
                "<path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z'/>"
                "</svg>"
                "</button>"
                "</td>"
            )
        else:
            accion_html = "<td class='px-3 py-2 text-center text-slate-300'>—</td>"
        rows_html.append(
            "<tr class='hover:bg-slate-50'>"
            f"<td class='px-3 py-2 font-mono text-xs text-slate-500 whitespace-nowrap'>{t.codigo or ''}</td>"
            f"<td class='px-3 py-2 text-xs text-slate-800 max-w-xs truncate' title='{t.titulo or ''}'>{t.titulo or ''}</td>"
            "<td class='px-3 py-2 text-xs'>"
            f"<span class='inline-flex items-center gap-1.5'>"
            f"<span class='w-2 h-2 rounded-full' style='background:{estado_color}'></span>"
            f"<span class='text-slate-700'>{estado_nombre}</span>"
            "</span></td>"
            f"<td class='px-3 py-2 text-xs'>{_fmt_resultado(t.resultado_pruebas)}</td>"
            f"<td class='px-3 py-2 text-xs text-slate-600'>{_fmt_item(t.item)}</td>"
            "<td class='px-3 py-2 text-xs'>"
            f"<span class='px-2 py-0.5 text-[10px] font-semibold rounded-full {prio_cls}'>{prio_label}</span>"
            "</td>"
            f"<td class='px-3 py-2 text-xs text-slate-600'>{asignado_nombre}</td>"
            f"<td class='px-3 py-2 text-xs text-slate-600 whitespace-nowrap'>{_fmt_fecha(t.fecha_vencimiento_sla)}</td>"
            f"{accion_html}"
            "</tr>"
        )

    total_count = len(rows_html)
    rows_str = "\n".join(rows_html) if rows_html else (
        "<tr><td colspan='9' class='px-4 py-10 text-center text-slate-400 text-sm'>"
        "No se encontraron tickets para esta combinación de módulo y resultado.</td></tr>"
    )

    color_cfg = CUENTA_RESULTADO_COLORES_PARA_MODAL.get(resultado_filtro)
    if color_cfg is None:
        color_cfg = {"bg": "#475569", "text": "#ffffff"}
    resultado_badge = (
        f"<span class='inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold' "
        f"style='background:{color_cfg['bg']}; color:{color_cfg['text']};'>{resultado_filtro}</span>"
    )

    html = f"""
<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 modal-backdrop"
     onclick="if(event.target===this) cerrarModalCuentaResultado()">
  <div class="bg-white rounded-xl shadow-2xl w-full max-w-6xl max-h-[85vh] flex flex-col overflow-hidden border border-slate-200"
       onclick="event.stopPropagation()">

    <!-- Header -->
    <div class="px-5 py-3 border-b border-slate-200 flex items-center justify-between gap-3 flex-wrap bg-slate-50">
      <div class="flex items-center gap-3 flex-wrap">
        <h3 class="text-sm font-semibold text-slate-800">Detalle de Cuenta de Resultado</h3>
        <div class="flex items-center gap-2 text-xs text-slate-500">
          <span class="text-[10px] uppercase tracking-wide text-slate-400">Módulo:</span>
          <span class="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold">{modulo_filtro}</span>
          <span class="text-[10px] uppercase tracking-wide text-slate-400">Resultado:</span>
          {resultado_badge}
          <span class="text-[10px] uppercase tracking-wide text-slate-400">Ambiente:</span>
          <span class="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold">{ambiente_filtro}</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 font-mono">{total_count} ticket(s)</span>
        <button type="button" onclick="cerrarModalCuentaResultado()"
                class="inline-flex items-center justify-center w-7 h-7 rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-700"
                title="Cerrar">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Tabla -->
    <div class="overflow-auto flex-1">
      <table class="w-full text-xs border-collapse">
        <thead class="bg-slate-100 text-[10px] uppercase text-slate-600 sticky top-0 z-10">
          <tr>
            <th class="px-3 py-2 text-left border-b border-slate-200">Código</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Título</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Estado</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Resultado Prueba</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Ítem</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Prioridad</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Asignado</th>
            <th class="px-3 py-2 text-left border-b border-slate-200">Fecha Vencimiento</th>
            <th class="px-3 py-2 text-center border-b border-slate-200" title="Ver y editar ticket individual">Acciones</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          {rows_str}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div class="px-5 py-2.5 border-t border-slate-200 bg-slate-50 text-[11px] text-slate-500 flex items-center justify-between">
      <span>Drill-down generado el {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</span>
      <span>Esc para cerrar</span>
    </div>
  </div>
</div>
"""
    return HTMLResponse(html)
