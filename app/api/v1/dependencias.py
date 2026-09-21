"""
Endpoints API para FEATURE 3: Dependencias Gantt + Import .mpp/XML.

Endpoints:
    POST   /api/v1/dependencias                  → crear
    GET    /api/v1/dependencias/ticket/{id}      → listar las de un ticket
    DELETE /api/v1/dependencias/{dep_id}         → eliminar
    POST   /api/v1/dependencias/importar-xml     → importar .mpp exportado
    GET    /api/v1/dependencias/xml-preview      → preview de import

Todos requieren sesión activa. La creación/eliminación/importación
requieren permiso ``configurar_butler`` o ser Administrador (el permiso
genérico para tocar configuración del sistema).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from markupsafe import escape as _esc
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_current_user
from app.models.ticket import Ticket
from app.models.ticket_dependencia import (
    TIPO_DEPENDENCIA_NOMBRES, TicketDependencia, TipoDependencia,
)
from app.models.usuario import Usuario, RolUsuario
from app.services.dependencia_service import (
    DependenciaError, MSProjectXMLParser, TicketDependenciaService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dependencias", tags=["dependencias"])


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _parse_msp_date(date_str: str) -> Optional[datetime]:
    """Parsea fechas en formato MS Project (``YYYY-MM-DDTHH:MM:SS``)
    devolviendo un ``datetime`` naive (UTC implícito). Si no se puede
    parsear, devuelve ``None``.
    """
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class DependenciaCreate(BaseModel):
    predecesor_id: int = Field(..., gt=0)
    sucesor_id: int = Field(..., gt=0)
    tipo: str = Field("fs", description="FS / SS / FF / SF")
    lag_dias: int = Field(0, ge=-365, le=365)
    nota: Optional[str] = None


class DependenciaRead(BaseModel):
    id: int
    predecesor_id: int
    predecesor_codigo: str
    predecesor_titulo: str
    sucesor_id: int
    sucesor_codigo: str
    sucesor_titulo: str
    tipo: str
    tipo_nombre: str
    lag_dias: int
    nota: Optional[str] = None

    class Config:
        from_attributes = True


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _requiere_admin_o_agente_senior(usuario: Usuario) -> None:
    """Sólo Admin y Agente Senior pueden crear/eliminar dependencias."""
    if usuario.rol not in (RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR):
        raise HTTPException(
            status_code=403,
            detail="Solo Administrador o Agente Senior pueden gestionar dependencias.",
        )


def _to_read(d: TicketDependencia) -> DependenciaRead:
    return DependenciaRead(
        id=d.id,
        predecesor_id=d.predecesor_id,
        predecesor_codigo=d.predecesor.codigo if d.predecesor else "?",
        predecesor_titulo=(d.predecesor.titulo if d.predecesor else "")[:80],
        sucesor_id=d.sucesor_id,
        sucesor_codigo=d.sucesor.codigo if d.sucesor else "?",
        sucesor_titulo=(d.sucesor.titulo if d.sucesor else "")[:80],
        tipo=d.tipo.value,
        tipo_nombre=TIPO_DEPENDENCIA_NOMBRES.get(d.tipo, d.tipo.value),
        lag_dias=d.lag_dias,
        nota=d.nota,
    )


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@router.post("", response_model=DependenciaRead, status_code=201)
def crear_dependencia(
    payload: DependenciaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea una nueva dependencia entre dos tickets."""
    _requiere_admin_o_agente_senior(usuario)
    svc = TicketDependenciaService(db)
    try:
        dep = svc.crear(
            predecesor_id=payload.predecesor_id,
            sucesor_id=payload.sucesor_id,
            tipo=payload.tipo,
            lag_dias=payload.lag_dias,
            nota=payload.nota,
        )
    except DependenciaError as e:
        raise HTTPException(status_code=400, detail={"codigo": e.codigo, "mensaje": e.mensaje})
    return _to_read(dep)


@router.get("/ticket/{ticket_id}", response_model=List[DependenciaRead])
def listar_dependencias_de_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista las dependencias (salientes + entrantes) de un ticket."""
    # Cualquier usuario autenticado puede VER las dependencias (necesario
    # para el Gantt).
    svc = TicketDependenciaService(db)
    deps = svc.listar_para_tickets([ticket_id])
    return [_to_read(d) for d in deps]


@router.get("/ticket-batch", response_model=List[DependenciaRead])
def listar_dependencias_para_batch(
    ids: str = Query(..., description="IDs separados por coma (ej: '1,2,3')"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todas las dependencias cuyo predecesor O sucesor esté en el set.

    Usado por el Gantt para alimentar las flechas de dependencia.
    """
    try:
        ids_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Lista de IDs inválida.")
    svc = TicketDependenciaService(db)
    deps = svc.listar_para_tickets(ids_list)
    return [_to_read(d) for d in deps]


@router.delete("/{dep_id}", status_code=204)
def eliminar_dependencia(
    dep_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _requiere_admin_o_agente_senior(usuario)
    svc = TicketDependenciaService(db)
    ok = svc.eliminar(dep_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Dependencia no encontrada.")
    return None


# -----------------------------------------------------------------------------
# Importador .mpp / XML
# -----------------------------------------------------------------------------
class ImportarXMLRequest(BaseModel):
    """Petición para importar dependencias desde XML de MS Project.

    El XML puede venir:
        - Como string en el campo ``xml_content`` (útil para tests o
          integraciones que ya tienen el texto en memoria).
        - Como archivo subido en un endpoint separado
          (``/dependencias/importar-xml-file``).
    """
    xml_content: str = Field(..., description="Contenido del XML exportado de MS Project.")
    dry_run: bool = Field(
        True,
        description="Si True, NO crea dependencias; sólo devuelve el preview.",
    )
    crear_tickets_faltantes: bool = Field(
        False,
        description="Si True, crea tickets para las tareas del XML que NO "
                    "existan en Bitácora (match por codigo + HU).",
    )
    actualizar_fechas: bool = Field(
        True,
        description="Si True, completa fecha_inicio y fecha_vencimiento_sla "
                    "de los tickets existentes a partir de las fechas del "
                    "XML. Esto es lo que hace que el Gantt muestre datos.",
    )


class ImportarXMLResponse(BaseModel):
    preview: bool
    tareas_xml: int
    tareas_conocidas: int
    tareas_a_crear: List[dict]
    tickets_creados: int = 0
    fechas_actualizadas: int = 0
    links_xml: int
    links_a_crear: List[dict]
    # === (C) Resumen ejecutivo de omitidos/errores ===
    # Por defecto NO devolvemos el listado completo de links_omitidos
    # (puede tener cientos de items y enmascara la señal). En su lugar,
    # devolvemos un conteo y una muestra de los primeros N para diagnóstico.
    # Si el cliente quiere el detalle completo, pasa ``?detallar_omitidos=true``.
    links_omitidos_count: int = 0
    links_omitidos_muestra: List[dict] = []
    errores: List[str]
    # Backwards compat: campo legacy (deprecado). Mantener en None
    # para no romper consumidores que ya lo lean.
    links_omitidos: Optional[List[dict]] = None


@router.post("/importar-xml", response_model=ImportarXMLResponse)
def importar_xml(
    payload: ImportarXMLRequest,
    detallar_omitidos: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Importa dependencias desde un XML de MS Project (.mpp exportado).

    Lógica:
        1. Parsea el XML (acepta formato A moderno y formato B legacy).
        2. Para cada ``<Task>`` busca un ticket existente matcheando por
           ``hu_o_caso_prueba`` o por ``codigo`` (estrategia case-insensitive
           en ambos sentidos).
        3. Si ``actualizar_fechas=True`` (default) y el ticket matcheado
           NO tiene ``fecha_inicio`` o ``fecha_vencimiento_sla``, los
           completa con las del XML. Esto es CRÍTICO para que el Gantt
           muestre datos.
        4. (B) Si ``crear_tickets_faltantes=True``, crea tickets para
           todas las tareas del XML que no matcheen con uno existente.
           Se asigna un código ``MP_<UID>`` y se copian las fechas del
           XML. Sólo se ejecuta si ``dry_run=False``.
        5. Para cada ``<PredecessorLink>`` con predecesor y sucesor
           conocidos, crea la dependencia (con el tipo FS/SS/FF/SF).
           (A) Defensa en profundidad: rechaza auto-dependencias
           (pred.id == suc.id) por si dos XML UIDs matchearon al mismo
           ticket.
        6. Si ``dry_run=True``, NO persiste; sólo reporta lo que haría.
        7. (C) Por defecto NO devuelve el array completo ``links_omitidos``
           (puede tener 100+ items). Devuelve ``links_omitidos_count`` y
           ``links_omitidos_muestra`` (primeros 10). Pasar
           ``?detallar_omitidos=true`` para el listado completo (debug).
    """
    _requiere_admin_o_agente_senior(usuario)

    # 1) Parsear
    parser = MSProjectXMLParser(payload.xml_content.encode("utf-8"))
    try:
        data = parser.parsear()
    except DependenciaError as e:
        raise HTTPException(status_code=400, detail={"codigo": e.codigo, "mensaje": e.mensaje})

    # 2) Indexar tickets existentes por UID-derivado:
    tickets = (
        db.query(Ticket)
        .filter(Ticket.archivado == False)  # noqa: E712
        .all()
    )

    def _match_ticket(tarea: dict) -> Optional[Ticket]:
        """Encuentra el ticket que corresponde a una tarea del XML."""
        # Estrategia 1: por hu_o_caso_prueba exacto (case-insensitive)
        hu_busqueda = (tarea.get("wbs") or tarea.get("name", "")).strip()
        if not hu_busqueda:
            return None
        for t in tickets:
            if t.hu_o_caso_prueba and t.hu_o_caso_prueba.strip().lower() == hu_busqueda.lower():
                return t
        # Estrategia 2: por código que contenga la WBS
        for t in tickets:
            if t.codigo and hu_busqueda and hu_busqueda.lower() in t.codigo.lower():
                return t
        # Estrategia 3: por nombre del ticket que contenga el name del XML
        name_busqueda = (tarea.get("name") or "").strip()
        if name_busqueda:
            for t in tickets:
                if t.titulo and name_busqueda.lower()[:25] in t.titulo.lower():
                    return t
        return None

    # Estado por defecto del nuevo ticket (intentamos un estado abierto
    # razonable; si la tabla de estados está vacía lo creamos al vuelo
    # para no romper el import en bases de datos recién inicializadas).
    def _ensure_default_estado(db: Session):
        from app.models.estado import Estado
        est = db.query(Estado).order_by(Estado.orden.asc()).first()
        if est:
            return est.id
        # Si no hay estados, creamos uno por defecto (no es ideal, pero
        # garantiza que el import no rompa por FK en bases vacías).
        from datetime import datetime as _dt
        est = Estado(nombre="Importado XML", orden=999, color="#6366f1")
        db.add(est)
        db.flush()
        return est.id

    # 3) Resolver tareas, completar fechas y (B) opcionalmente crear
    #    tickets nuevos para las tareas del XML que no matcheen.
    tareas_conocidas = 0
    mapa_uid_a_ticket = {}  # uid_xml → Ticket
    tareas_a_crear = []     # preview (cuando dry_run=True)
    tickets_creados = 0     # ejecuciones reales (cuando dry_run=False)
    fechas_actualizadas = 0
    errores: List[str] = []  # acumulado de errores a nivel de tareas / persistencia

    crear_nuevos = bool(payload.crear_tickets_faltantes and not payload.dry_run)

    # (B) Si vamos a crear tickets, pre-asignamos IDs del estado por
    # defecto para evitar N round-trips al motor.
    default_estado_id = None
    if crear_nuevos:
        try:
            default_estado_id = _ensure_default_estado(db)
        except Exception as e:
            errores.append(f"No se pudo obtener estado por defecto: {e}")
            crear_nuevos = False

    for tarea in data["tareas"]:
        t = _match_ticket(tarea)
        if t:
            mapa_uid_a_ticket[tarea["uid"]] = t
            tareas_conocidas += 1
            # Completar fechas si está habilitado y faltan en el ticket.
            if payload.actualizar_fechas and not payload.dry_run:
                inicio_dt = _parse_msp_date(tarea.get("start"))
                fin_dt = _parse_msp_date(tarea.get("finish"))
                if inicio_dt and not t.fecha_inicio:
                    t.fecha_inicio = inicio_dt
                    fechas_actualizadas += 1
                if fin_dt and not t.fecha_vencimiento_sla:
                    t.fecha_vencimiento_sla = fin_dt
                    fechas_actualizadas += 1
            continue

        # No matcheó: previsualizar o crear.
        if not crear_nuevos:
            # En modo preview, dejamos que `links_omitidos` reporte el
            # problema a nivel de links.
            tareas_a_crear.append({
                "uid": tarea["uid"],
                "name": tarea["name"],
                "wbs": tarea["wbs"],
                "start": tarea["start"],
                "finish": tarea["finish"],
                "duration_hours": tarea["duration_hours"],
            })
            continue

        # (B) Crear ticket nuevo.
        wbs = (tarea.get("wbs") or "").strip()
        name = (tarea.get("name") or "Tarea importada").strip()
        uid = tarea["uid"]
        codigo = f"MP_{uid}"
        # Salvaguardas: si ya existe un ticket con ese código (poco probable
        # porque ya falló el match), lo saltamos y dejamos que se reporte
        # como omitido en links.
        existing = db.query(Ticket).filter(Ticket.codigo == codigo).first()
        if existing:
            mapa_uid_a_ticket[uid] = existing
            continue
        nuevo = Ticket(
            codigo=codigo,
            titulo=name[:200],
            descripcion=(
                f"Ticket creado automáticamente al importar XML MS Project.\n"
                f"UID: {uid}\nWBS: {wbs}\nDuración (h): "
                f"{tarea.get('duration_hours')}"
            ),
            estado_id=default_estado_id,
            creador_id=usuario.id,
            hu_o_caso_prueba=wbs or None,
            archivado=False,
            fecha_inicio=_parse_msp_date(tarea.get("start")),
            fecha_vencimiento_sla=_parse_msp_date(tarea.get("finish")),
        )
        db.add(nuevo)
        try:
            db.flush()  # para obtener el ID
        except Exception as e:
            db.rollback()
            errores.append(f"No se pudo crear ticket para UID={uid}: {e}")
            continue
        # Lo añadimos al índice para que el match de los links funcione.
        tickets.append(nuevo)
        mapa_uid_a_ticket[uid] = nuevo
        tickets_creados += 1

    # Persistir los cambios de fechas y tickets nuevos (un solo commit).
    if (fechas_actualizadas or tickets_creados) and not payload.dry_run:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            errores.append(f"Error al persistir cambios: {e}")

    # 4) Resolver links
    svc = TicketDependenciaService(db)
    links_a_crear = []
    links_omitidos = []     # completo (sólo si detallar_omitidos=True)
    links_omitidos_muestra = []  # primeros 10
    errores_links = []
    for link in data["links"]:
        pred = mapa_uid_a_ticket.get(link["predecesor_uid"])
        suc = mapa_uid_a_ticket.get(link["sucesor_uid"])
        # (A) Auto-dependencia: defensa en profundidad. Si dos UIDs del
        # XML matchearon al MISMO ticket (matching laxo), no creamos un
        # loop A→A. Lo registramos como omitido con motivo claro.
        if pred is not None and suc is not None and pred.id == suc.id:
            entrada = {
                "predecesor_uid": link["predecesor_uid"],
                "sucesor_uid": link["sucesor_uid"],
                "predecesor_codigo": pred.codigo,
                "motivo": "auto_dependencia",
            }
            links_omitidos.append(entrada)
            if len(links_omitidos_muestra) < 10:
                links_omitidos_muestra.append(entrada)
            continue
        if not pred or not suc:
            entrada = {
                "predecesor_uid": link["predecesor_uid"],
                "sucesor_uid": link["sucesor_uid"],
                "motivo": "ticket_no_encontrado",
            }
            links_omitidos.append(entrada)
            if len(links_omitidos_muestra) < 10:
                links_omitidos_muestra.append(entrada)
            continue
        if payload.dry_run:
            links_a_crear.append({
                "predecesor_codigo": pred.codigo,
                "sucesor_codigo": suc.codigo,
                "tipo": link["tipo_str"],
                "lag_dias": link["lag_dias"],
            })
        else:
            try:
                dep = svc.crear(
                    predecesor_id=pred.id,
                    sucesor_id=suc.id,
                    tipo=link["tipo_str"],
                    lag_dias=link["lag_dias"],
                    nota=f"Importado XML MS Project (uid_pred={link['predecesor_uid']})",
                )
                links_a_crear.append({
                    "predecesor_codigo": pred.codigo,
                    "sucesor_codigo": suc.codigo,
                    "tipo": link["tipo_str"],
                    "lag_dias": link["lag_dias"],
                    "dep_id": dep.id,
                })
            except DependenciaError as e:
                errores_links.append(f"{pred.codigo}→{suc.codigo}: {e.mensaje}")

    # Si no queremos detallar, NO emitimos el array completo para no
    # contaminar el payload. Devolvemos None en el campo legacy y los
    # campos-resumen.
    todos_los_errores = errores + errores_links
    return ImportarXMLResponse(
        preview=payload.dry_run,
        tareas_xml=len(data["tareas"]),
        tareas_conocidas=tareas_conocidas,
        tareas_a_crear=tareas_a_crear,
        tickets_creados=tickets_creados,
        fechas_actualizadas=fechas_actualizadas,
        links_xml=len(data["links"]),
        links_a_crear=links_a_crear,
        links_omitidos_count=len(links_omitidos),
        links_omitidos_muestra=links_omitidos_muestra,
        errores=todos_los_errores,
        links_omitidos=(links_omitidos if detallar_omitidos else None),
    )


@router.post("/importar-xml-file", response_model=ImportarXMLResponse)
async def importar_xml_file(
    file: UploadFile = File(...),
    dry_run: bool = True,
    crear_tickets_faltantes: bool = False,
    actualizar_fechas: bool = True,
    detallar_omitidos: bool = False,
    render: Optional[str] = Query(
        None,
        description="Si se pasa 'html', devuelve un reporte HTML "
                    "(HTMLResponse) en lugar de JSON. Pensado para uso "
                    "directo desde HTMX en el modal de import del Gantt.",
    ),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Importa dependencias desde un archivo .xml/.mpp subido.

    Modos:
        - Default: devuelve ``ImportarXMLResponse`` en JSON (uso API).
        - ``?render=html``: devuelve un fragmento HTML listo para hacer
          swap con HTMX en el modal de import del Gantt.
    """
    _requiere_admin_o_agente_senior(usuario)
    contenido = await file.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="Archivo vacío.")
    payload = ImportarXMLRequest(
        xml_content=contenido.decode("utf-8", errors="replace"),
        dry_run=dry_run,
        crear_tickets_faltantes=crear_tickets_faltantes,
        actualizar_fechas=actualizar_fechas,
    )
    resultado = importar_xml(
        payload,
        detallar_omitidos=detallar_omitidos,
        db=db,
        usuario=usuario,
    )

    if render == "html":
        html = _render_importar_xml_html(resultado, payload, filename=file.filename or "")
        return HTMLResponse(html)

    return resultado


# -----------------------------------------------------------------------------
# Renderizador HTML del resultado de import (uso HTMX)
# -----------------------------------------------------------------------------
_TIPO_BADGE = {
    "fs": ("FS", "bg-indigo-100 text-indigo-800", "Fin → Inicio"),
    "ss": ("SS", "bg-amber-100 text-amber-800",   "Inicio → Inicio"),
    "ff": ("FF", "bg-emerald-100 text-emerald-800", "Fin → Fin"),
    "sf": ("SF", "bg-pink-100 text-pink-800",     "Inicio → Fin"),
}

_MOTIVO_BADGE = {
    "ticket_no_encontrado": ("Ticket no encontrado", "bg-rose-100 text-rose-800"),
    "auto_dependencia":     ("Auto-dependencia (A→A)", "bg-amber-100 text-amber-800"),
}


def _badge(label: str, cls: str) -> str:
    return (
        f'<span class="inline-flex items-center px-2 py-0.5 rounded text-xs '
        f'font-semibold {cls}">{_esc(label)}</span>'
    )


def _render_importar_xml_html(
    resultado: "ImportarXMLResponse",
    payload: "ImportarXMLRequest",
    filename: str = "",
) -> str:
    """Construye un fragmento HTML con el reporte del import, listo para
    ``hx-swap="innerHTML"`` dentro del modal de import del Gantt.

    Estructura:
        1. Banner de modo (preview / aplicado).
        2. Grid de 5 KPIs (tareas / conocidas / a crear / links / omitidos).
        3. Errores (si hay).
        4. Tabla ``Tareas a crear`` colapsable.
        5. Tabla ``Links a crear`` colapsable.
        6. Lista ``Links omitidos (muestra)`` colapsable.
    """
    es_preview = bool(resultado.preview)
    tareas_a_crear = resultado.tareas_a_crear or []
    links_a_crear  = resultado.links_a_crear  or []
    errores        = resultado.errores        or []
    muestra        = resultado.links_omitidos_muestra or []
    omitidos_count = resultado.links_omitidos_count or 0

    # ---- Banner de modo ----
    if es_preview:
        banner = (
            '<div class="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 '
            'flex items-center gap-2 text-sm text-sky-900">'
            '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" '
            'viewBox="0 0 24 24"><path stroke-linecap="round" '
            'stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01'
            'M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
            '<span><b>Modo preview.</b> No se guardaron cambios. Desmarca '
            '"Solo preview" y vuelve a importar para aplicar.</span></div>'
        )
    else:
        banner = (
            '<div class="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 '
            'flex items-center gap-2 text-sm text-emerald-900">'
            '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" '
            'viewBox="0 0 24 24"><path stroke-linecap="round" '
            'stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>'
            '<span><b>Importación aplicada.</b> Cambios persistidos en la base '
            'de datos.</span></div>'
        )

    # ---- KPIs ----
    pct_conocidas = (
        f"{(resultado.tareas_conocidas / resultado.tareas_xml * 100):.0f}%"
        if resultado.tareas_xml else "—"
    )
    pct_links_ok = (
        f"{len(links_a_crear) / max(resultado.links_xml, 1) * 100:.0f}%"
        if resultado.links_xml else "—"
    )

    kpi_cards = [
        ("Tareas en XML", str(resultado.tareas_xml), "slate"),
        (f"Reconocidas ({pct_conocidas})", str(resultado.tareas_conocidas), "emerald"),
        ("Tickets a crear", str(len(tareas_a_crear)), "amber" if tareas_a_crear else "slate"),
        (f"Links a crear ({pct_links_ok})", str(len(links_a_crear)), "indigo"),
        ("Links omitidos", str(omitidos_count), "rose" if omitidos_count else "slate"),
    ]
    color_map = {
        "slate":   ("bg-slate-50 border-slate-200 text-slate-700",   "text-slate-900"),
        "emerald": ("bg-emerald-50 border-emerald-200 text-emerald-700", "text-emerald-900"),
        "amber":   ("bg-amber-50 border-amber-200 text-amber-700",   "text-amber-900"),
        "indigo":  ("bg-indigo-50 border-indigo-200 text-indigo-700", "text-indigo-900"),
        "rose":    ("bg-rose-50 border-rose-200 text-rose-700",       "text-rose-900"),
    }
    kpis_html = '<div class="grid grid-cols-2 sm:grid-cols-5 gap-2">'
    for label, value, color in kpi_cards:
        bg, fg = color_map[color]
        kpis_html += (
            f'<div class="rounded-lg border {bg} px-3 py-2">'
            f'<div class="text-[11px] font-medium uppercase tracking-wide opacity-80">{_esc(label)}</div>'
            f'<div class="text-xl font-bold {fg}">{_esc(value)}</div>'
            f'</div>'
        )
    kpis_html += "</div>"

    # Info adicional (tickets creados + fechas actualizadas)
    extras = []
    if resultado.tickets_creados:
        extras.append(
            f'<span class="inline-flex items-center gap-1">'
            f'<b class="text-emerald-700">{resultado.tickets_creados}</b> '
            f'ticket(s) nuevo(s) creado(s)</span>'
        )
    if resultado.fechas_actualizadas:
        extras.append(
            f'<span class="inline-flex items-center gap-1">'
            f'<b class="text-emerald-700">{resultado.fechas_actualizadas}</b> '
            f'fecha(s) actualizada(s)</span>'
        )
    if filename:
        extras.append(
            f'<span class="inline-flex items-center gap-1 text-slate-500">'
            f'<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            f'd="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>'
            f'<span class="truncate max-w-[260px]" title="{_esc(filename)}">{_esc(filename)}</span>'
            f'</span>'
        )
    extras_html = (
        '<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">' + "".join(extras) + "</div>"
        if extras else ""
    )

    # ---- Sección errores ----
    if errores:
        errores_html = (
            '<details open class="rounded-lg border border-rose-200 bg-rose-50">'
            '<summary class="cursor-pointer px-3 py-2 text-sm font-semibold text-rose-800 '
            'flex items-center gap-2">'
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 '
            '00-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z"/></svg>'
            f'Errores ({len(errores)})</summary>'
            '<ul class="px-5 py-2 text-xs text-rose-900 list-disc space-y-0.5 max-h-40 overflow-y-auto">'
            + "".join(f"<li>{_esc(e)}</li>" for e in errores)
            + "</ul></details>"
        )
    else:
        errores_html = ""

    # ---- Tabla de tareas a crear ----
    if tareas_a_crear:
        rows = []
        # Cabecera sticky dentro de un contenedor scrollable
        body_rows = []
        for t in tareas_a_crear:
            uid   = t.get("uid", "—")
            name  = t.get("name", "")
            wbs   = t.get("wbs", "—")
            inicio = (t.get("start") or "")[:10]
            fin    = (t.get("finish") or "")[:10]
            dur    = t.get("duration_hours", "")
            if dur not in (None, ""):
                try:
                    dur = f"{float(dur):.0f} h"
                except (TypeError, ValueError):
                    dur = str(dur)
            body_rows.append(
                "<tr class='border-t border-slate-100'>"
                f"<td class='px-2 py-1 text-slate-500 text-[11px]'>{_esc(str(uid))}</td>"
                f"<td class='px-2 py-1 font-mono text-[11px] text-slate-600'>{_esc(str(wbs))}</td>"
                f"<td class='px-2 py-1 text-xs'>{_esc(name)}</td>"
                f"<td class='px-2 py-1 text-[11px] text-slate-600 whitespace-nowrap'>{_esc(inicio)}</td>"
                f"<td class='px-2 py-1 text-[11px] text-slate-600 whitespace-nowrap'>{_esc(fin)}</td>"
                f"<td class='px-2 py-1 text-[11px] text-slate-600 text-right'>{_esc(str(dur))}</td>"
                "</tr>"
            )
        # Si hay más de 30, colapsamos por defecto y ponemos scroll interno.
        total_t = len(tareas_a_crear)
        open_attr = "open" if total_t <= 5 else ""
        max_h = "max-h-72" if total_t > 30 else ""
        tareas_html = (
            '<details class="rounded-lg border border-amber-200 bg-white" '
            f'{open_attr}>'
            '<summary class="cursor-pointer px-3 py-2 text-sm font-semibold '
            'text-amber-900 bg-amber-50 border-b border-amber-200 '
            'flex items-center gap-2">'
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M12 4v16m8-8H4"/></svg>'
            f'Tareas a crear ({total_t})'
            '<span class="ml-auto text-[11px] font-normal text-amber-700">'
            'Crea los tickets faltantes si activas esa opción</span>'
            '</summary>'
            '<div class="overflow-x-auto ' + max_h + ' overflow-y-auto">'
            '<table class="min-w-full text-sm">'
            '<thead class="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wide '
            'text-slate-500">'
            '<tr>'
            '<th class="px-2 py-1 text-left">UID</th>'
            '<th class="px-2 py-1 text-left">WBS</th>'
            '<th class="px-2 py-1 text-left">Nombre</th>'
            '<th class="px-2 py-1 text-left">Inicio</th>'
            '<th class="px-2 py-1 text-left">Fin</th>'
            '<th class="px-2 py-1 text-right">Duración</th>'
            '</tr></thead>'
            '<tbody>' + "".join(body_rows) + '</tbody></table></div></details>'
        )
    else:
        tareas_html = (
            '<div class="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 '
            'text-sm text-emerald-800 flex items-center gap-2">'
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M5 13l4 4L19 7"/></svg>'
            'Todas las tareas del XML matchearon con tickets existentes.'
            '</div>'
        )

    # ---- Tabla de links a crear ----
    if links_a_crear:
        body_rows = []
        for link in links_a_crear:
            tipo_raw = (link.get("tipo") or "fs").lower()
            tipo_badge = _TIPO_BADGE.get(
                tipo_raw,
                (tipo_raw.upper(), "bg-slate-100 text-slate-700", tipo_raw.upper()),
            )
            lag = link.get("lag_dias", 0)
            lag_str = f"+{lag}d" if lag > 0 else (f"{lag}d" if lag else "0d")
            body_rows.append(
                "<tr class='border-t border-slate-100'>"
                f"<td class='px-2 py-1 font-mono text-[11px] text-slate-700'>{_esc(link.get('predecesor_codigo', '—'))}</td>"
                "<td class='px-2 py-1 text-center text-slate-400'>→</td>"
                f"<td class='px-2 py-1 font-mono text-[11px] text-slate-700'>{_esc(link.get('sucesor_codigo', '—'))}</td>"
                f"<td class='px-2 py-1 text-center'>{_badge(tipo_badge[0], tipo_badge[1])}</td>"
                f"<td class='px-2 py-1 text-center text-[11px] text-slate-600'>{_esc(lag_str)}</td>"
                "</tr>"
            )
        total_l = len(links_a_crear)
        open_attr = "open" if total_l <= 10 else ""
        max_h = "max-h-72" if total_l > 30 else ""
        links_html = (
            '<details class="rounded-lg border border-indigo-200 bg-white" '
            f'{open_attr}>'
            '<summary class="cursor-pointer px-3 py-2 text-sm font-semibold '
            'text-indigo-900 bg-indigo-50 border-b border-indigo-200 '
            'flex items-center gap-2">'
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M13.828 10.172a4 4 0 015.656 0l1.415 1.415a4 4 0 010 5.656l-3 3a4 4 0 '
            '01-5.656 0M10.172 13.828a4 4 0 01-5.656 0l-1.415-1.415a4 4 0 010-5.656l3-3a4 4 0 015.656 0"/></svg>'
            f'Links / dependencias a crear ({total_l})</summary>'
            '<div class="overflow-x-auto ' + max_h + ' overflow-y-auto">'
            '<table class="min-w-full text-sm">'
            '<thead class="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wide '
            'text-slate-500">'
            '<tr>'
            '<th class="px-2 py-1 text-left">Predecesor</th>'
            '<th class="px-2 py-1"></th>'
            '<th class="px-2 py-1 text-left">Sucesor</th>'
            '<th class="px-2 py-1 text-center">Tipo</th>'
            '<th class="px-2 py-1 text-center">Lag</th>'
            '</tr></thead>'
            '<tbody>' + "".join(body_rows) + '</tbody></table></div></details>'
        )
    else:
        links_html = (
            '<div class="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 '
            'text-sm text-slate-700">Sin links a crear.</div>'
        )

    # ---- Lista de links omitidos (muestra) ----
    if omitidos_count:
        items = []
        for m in muestra:
            motivo_key = m.get("motivo", "")
            motivo_badge = _MOTIVO_BADGE.get(
                motivo_key,
                (motivo_key or "—", "bg-slate-100 text-slate-700"),
            )
            pred_cod = m.get("predecesor_codigo") or f"UID {m.get('predecesor_uid', '?')}"
            suc_uid  = m.get("sucesor_uid", "?")
            items.append(
                "<li class='flex items-center gap-2 py-1 border-t border-slate-100 first:border-0'>"
                f"<span class='font-mono text-[11px] text-slate-600'>{_esc(str(pred_cod))}</span>"
                f"<span class='text-slate-400'>→</span>"
                f"<span class='font-mono text-[11px] text-slate-600'>UID {_esc(str(suc_uid))}</span>"
                f"{_badge(motivo_badge[0], motivo_badge[1])}"
                "</li>"
            )
        mas = (
            f'<span class="text-[11px] text-slate-500 italic">'
            f'+{omitidos_count - len(muestra)} omitidos más (no mostrados)</span>'
            if omitidos_count > len(muestra) else ""
        )
        open_attr = "open" if omitidos_count <= 5 else ""
        omitidos_html = (
            '<details class="rounded-lg border border-rose-200 bg-white" '
            f'{open_attr}>'
            '<summary class="cursor-pointer px-3 py-2 text-sm font-semibold '
            'text-rose-900 bg-rose-50 border-b border-rose-200 '
            'flex items-center gap-2">'
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 '
            '5.636m12.728 12.728L5.636 5.636"/></svg>'
            f'Links omitidos ({omitidos_count}) — muestra de {len(muestra)}</summary>'
            '<ul class="px-3 py-1 text-sm">' + "".join(items) + mas + '</ul>'
            '</details>'
        )
    else:
        omitidos_html = (
            '<div class="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 '
            'text-sm text-emerald-800 flex items-center gap-2">'
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M5 13l4 4L19 7"/></svg>'
            'Ningún link omitido. Todos los pares predecesor/sucesor se encontraron.'
            '</div>'
        )

    # ---- Ensamblaje final ----
    return (
        '<div class="space-y-3" id="import-report">'
        + banner
        + kpis_html
        + (f'<div class="mt-2">{extras_html}</div>' if extras_html else "")
        + (f'<div class="mt-1">{errores_html}</div>' if errores_html else "")
        + f'<div class="mt-1">{tareas_html}</div>'
        + f'<div>{links_html}</div>'
        + f'<div>{omitidos_html}</div>'
        + '</div>'
    )
