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
    # DESESTIMADA se incluye explícitamente para que los tickets con ese
    # resultado_pruebas NO queden excluidos del pivot.
    columnas_front = [
        "N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA",
        "(en blanco)",
    ]

    # Mapeo: nombre canónico en front → variantes literales aceptadas en
    # ``tickets.resultado_pruebas``. Cada columna del pivot acepta TODAS
    # las variantes equivalentes para no perder tickets por nomenclatura
    # heredada, mayúsculas distintas o espacios accidentales
    # (regresión detectada 2026-09-17: tickets cuyo valor en BD era
    # ``"OK CON OBS"`` sin punto final NO aparecían en la columna
    # ``OK CON OBS.`` del pivot, deformando laCuenta de Resultado).
    #
    # Si en el futuro se agregan nuevos valores al LOV, basta con sumarlos
    # a su variante correspondiente aquí y (si son variantes distintas)
    # crear una nueva entrada en ``columnas_front``.
    def _eq_ci(*literales):
        """Construye una condición SQL case-insensitive y tolerante a
        espacios que matchee si ``resultado_pruebas`` normalizado coincide
        con cualquiera de los literales dados."""
        from sqlalchemy import or_
        norm = func.upper(func.trim(Ticket.resultado_pruebas))
        return or_(*[norm == lit.upper() for lit in literales])

    sql_columnas = [
        ("N/A",          _eq_ci("N/A")),
        ("NOK",          _eq_ci("NOK")),
        ("OK",           _eq_ci("OK")),
        # "OK CON OBS." es el LOV canónico pero aceptamos también las
        # variantes sin punto, con tilde/tilde invertida, plural, etc.
        ("OK CON OBS.",  _eq_ci(
            "OK CON OBS.", "OK CON OBS", "OK CON OBSERVACIONES",
            "OK CON OBSERVACIÓN", "OK CON OBSERVACION",
            "OK CON OBSERV.", "OK C/OBS", "OK COBS",
        )),
        # POSTERGADA / POSTERGADA A GARANTÍA (legacy) van juntas porque
        # la migración UAT normalizó a la forma corta.
        ("POSTERGADA",   _eq_ci(
            "POSTERGADA", "POSTERGADA A GARANTÍA",
            "POSTERGADA A GARANTIA", "POSTERGADO",
        )),
        ("DESESTIMADA",  _eq_ci("DESESTIMADA", "DESESTIMADO")),
        # NULL / cadena vacía / sólo espacios.
        ("(en blanco)",  Ticket.resultado_pruebas.is_(None) | (func.trim(Ticket.resultado_pruebas) == "")),  # noqa: E501
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

    # Normalizar filas: módulo NULL o vacío → "(en blanco)". También
    # agrupamos variantes conocidas (ej: "Registro Información" sin
    # "de" → "Registro de Información") bajo la misma etiqueta canónica
    # para que el pivot no muestre filas duplicadas por motivos de
    # nomenclatura heredada de la migración UAT.
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
        # Acumular en la fila canónica (puede que ya exista si había
        # múltiples variantes del mismo módulo).
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

    # Convertir dict a lista y ordenar con "(en blanco)" al final.
    filas_ordenadas = sorted(
        filas.values(),
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


@router.get("/cuenta-resultado/detalle")
def cuenta_resultado_detalle(
    modulo: str,
    resultado: str,
    ambiente: str = "QA",
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Drill-down: devuelve el HTML con el detalle de tickets de una celda del pivot.

    Endpoint consumido por HTMX al hacer clic en cualquier celda numérica
    de la tabla "Cuenta de Resultado" del Dashboard. Replica el
    comportamiento de doble-clic en una tabla dinámica Excel: muestra
    las filas (tickets) que componen el valor agregado de la celda.

    Query params:
      - ``modulo``:     etiqueta de fila del pivot (ej: ``"Auditoría"``,
                        ``"(en blanco)"`` para tickets sin módulo).
      - ``resultado``:  etiqueta de columna del pivot (ej: ``"OK"``,
                        ``"(en blanco)"`` para tickets sin resultado).
      - ``ambiente``:   filtro de ambiente (default ``"QA"``).

    Respuesta: fragmento HTML (no JSON) que el front inyecta dentro
    del modal. Incluye el contexto del filtro aplicado (módulo y
    resultado) en el header para que el usuario entienda qué celda
    está inspeccionando.
    """
    from fastapi.responses import HTMLResponse
    from app.models.ticket import Prioridad

    # Validación básica de parámetros: si vienen vacíos los tratamos como
    # la categoría "(en blanco)" del pivot. Nunca devolvemos TODOS los
    # tickets por accidente.
    modulo_filtro = (modulo or "").strip()
    resultado_filtro = (resultado or "").strip()
    ambiente_filtro = (ambiente or "QA").strip().upper()
    if ambiente_filtro not in ("QA", "PRODUCCION"):
        ambiente_filtro = "QA"

    # === Filtro de MÓDULO ===
    # Aplicamos la misma normalización que en ``cuenta_resultado``: si el
    # usuario pide "(en blanco)" buscamos tickets SIN módulo; si pide un
    # módulo canónico (ej: "Registro de Información") incluimos también
    # sus variantes conocidas (mapeadas en MODULO_ALIAS) para no perder
    # filas por nomenclatura heredada de la migración UAT.
    if modulo_filtro == "(en blanco)":
        modulo_cond = Ticket.modulo.is_(None) | (func.trim(Ticket.modulo) == "")
    else:
        # Construimos una condición OR: módulo igual al canónico O igual
        # a cualquiera de sus variantes en MODULO_ALIAS invertidas.
        from sqlalchemy import or_
        variantes = [modulo_filtro]
        for alias, canonico in MODULO_ALIAS.items():
            if canonico == modulo_filtro:
                variantes.append(alias)
        # También contemplamos el caso inverso: si el front pidió la
        # variante "alias" sin pasar por la normalización (defensa).
        for alias, canonico in MODULO_ALIAS.items():
            if alias == modulo_filtro:
                variantes.append(canonico)
        modulo_cond = or_(*[
            func.upper(func.trim(Ticket.modulo)) == v.upper()
            for v in variantes
        ])

    # === Filtro de RESULTADO PRUEBAS ===
    # Misma normalización case-insensitive + tolerante a variantes que
    # en ``cuenta_resultado`` (N/A, NOK, OK, OK CON OBS., POSTERGADA,
    # DESESTIMADA, o "(en blanco)" para NULL/vacío). Usamos la misma
    # tabla ``sql_columnas`` de arriba para mantener consistencia: si
    # agregamos un valor al LOV, sólo hay que tocar la lista.
    resultado_norm = func.upper(func.trim(Ticket.resultado_pruebas))

    # Mapeo explícito de cada etiqueta canónica → set de literales
    # aceptados. Idéntico al de ``cuenta_resultado`` para que el drill-down
    # muestre exactamente los mismos tickets que cuenta la celda del pivot.
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
        # Valor desconocido → 0 filas en vez de explotar.
        resultado_cond = func.upper(func.trim(Ticket.resultado_pruebas)) == resultado_filtro.upper()

    # === Query de tickets ===
    # Hacemos JOIN con Estado (para nombre+color) y con Usuario asignado
    # (para nombre_completo). Ordenamos por código ascendente para que el
    # drill-down sea estable entre recargas.
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

    # === Helpers de presentación ===
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

    # === Render del HTML ===
    # Header del modal: muestra qué celda se está inspeccionando.
    rows_html = []
    for t, estado, asignado in tickets_q:
        prio_cls, prio_label = _color_prioridad(t.prioridad)
        estado_nombre = estado.nombre if estado else "—"
        estado_color = estado.color if (estado and estado.color) else "#94a3b8"
        asignado_nombre = asignado.nombre_completo if asignado else "—"
        # Botón "Ver" que abre el detalle completo del ticket individual
        # (reusa /api/v1/tickets/{id}/detalle-html que ya devuelve el modal
        # con tabs de detalles/comentarios/adjuntos/auditorías). El target
        # es el MISMO contenedor del modal drill-down, así HTMX reemplaza
        # la lista por el detalle del ticket (que ya trae su propio
        # backdrop y botón cerrar).
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

    # Badge con color del resultado en el header del modal.
    color_cfg = CUENTA_RESULTADO_COLORES_PARA_MODAL.get(resultado_filtro)
    if color_cfg is None:
        # Fallback: si el resultado no está en el mapeo conocido, usamos
        # slate para no romper el modal.
        color_cfg = {"bg": "#475569", "text": "#ffffff"}
    resultado_badge = (
        f"<span class='inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold' "
        f"style='background:{color_cfg['bg']}; color:{color_cfg['text']};'>{resultado_filtro}</span>"
    )

    # El contenedor devuelto lleva TODO el modal (overlay + tarjeta). El
    # front lo inyecta en #modal-cuenta-resultado-root. El backdrop
    # permite cerrar haciendo clic fuera de la tarjeta (handler en JS).
    html = f"""
<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4"
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


# Mapa de colores para el badge del modal. Réplica (sólo bg + text) del
# objeto JS ``CUENTA_RESULTADO_COLORES`` que usa la tabla del Dashboard,
# para que el header del modal muestre el MISMO color que el header de
# la columna del pivot. Mantener sincronizado con el front.
CUENTA_RESULTADO_COLORES_PARA_MODAL = {
    "N/A":         {"bg": "#94a3b8", "text": "#ffffff"},
    "NOK":         {"bg": "#dc2626", "text": "#ffffff"},
    "OK":          {"bg": "#16a34a", "text": "#ffffff"},
    "OK CON OBS.": {"bg": "#eab308", "text": "#1f2937"},
    "POSTERGADA":  {"bg": "#ea580c", "text": "#ffffff"},
    "DESESTIMADA": {"bg": "#7c3aed", "text": "#ffffff"},
    "(en blanco)": {"bg": "#cbd5e1", "text": "#475569"},
}
