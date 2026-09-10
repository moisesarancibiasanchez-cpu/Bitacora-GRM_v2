"""
Aplicación principal FastAPI - Bitácora GRM.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.router import api_router
from app.core.config import settings

# Importante: importar whitenoise SOLO si está disponible. Si falta el
# paquete (modo dev minimalista) caemos al StaticFiles de FastAPI.
try:
    from whitenoise import WhiteNoise
    HAS_WHITENOISE = True
except ImportError:  # pragma: no cover
    HAS_WHITENOISE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización al arranque.

    1) SIEMPRE: aplicar migraciones pendientes (idempotente, rápido, seguro).
       Esto alinea el esquema de la BD con los modelos SQLAlchemy sin
       necesidad de Alembic. Se ejecuta en cada arranque para que un
       deploy que añada columnas no rompa la app en producción.

    2) SOLO SI AUTO_INIT_DB=true o DEBUG: ejecutar init_database() que crea
       tablas faltantes y carga datos semilla. En producción NO es
       necesario porque las migraciones del paso 1 ya garantizan el
       esquema; AUTO_INIT_DB solo se activa explícitamente.
    """
    # Paso 1: migraciones idempotentes (SIEMPRE)
    try:
        from app.db.migrations import apply_migrations
        apply_migrations()
    except Exception as e:
        logger.warning(f"[startup] No se pudieron aplicar migraciones: {e}")

    # Paso 2: init completo solo si está activado
    if settings.DEBUG or os.getenv("AUTO_INIT_DB", "false").lower() == "true":
        try:
            from app.db.init_db import init_database
            init_database()
        except Exception as e:
            logger.warning(f"[startup] No se pudo inicializar la BD automáticamente: {e}")
    yield


app = FastAPI(
    title="Bitácora GRM",
    description="Sistema híbrido ITSM + Kanban para gestión de incidencias",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# === Middlewares ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Archivos estáticos (StaticFiles siempre; WhiteNoise opcional en prod) ===
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# En dev y prod servimos /static con StaticFiles. En producción, si
# WhiteNoise está disponible, lo añadimos al final para aportar
# compresión brotli/gzip y caché de cabeceras.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# === Templates ===
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Registrar filtros personalizados (truncate_text, etc.).
# Esto se hace aquí para que estén disponibles en TODAS las plantillas
# Jinja2 (kanban, tickets, dashboard, etc.) sin necesidad de reimportar.
from app.core.jinja_filters import ALL_FILTERS  # noqa: E402

for _fname, _ffunc in ALL_FILTERS.items():
    templates.env.filters[_fname] = _ffunc


# === Routers API ===
app.include_router(api_router, prefix="/api/v1")


# === Rutas de páginas (HTML server-rendered) ===
def _get_usuario_actual(request: Request):
    """Resuelve el usuario actual a partir ÚNICAMENTE de la cookie ``access_token``.

    Retorna el ``Usuario`` autenticado o ``None`` si no hay sesión válida.
    NO hay fallback a 'primer admin' ni a 'modo demo' por seguridad:
    un usuario sin sesión debe ser redirigido a /auth/login.
    """
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario
    from app.core.security import decode_access_token
    db = SessionLocal()
    try:
        token = request.cookies.get("access_token")
        if not token:
            return None
        payload = decode_access_token(token)
        if not payload or "sub" not in payload:
            return None
        try:
            uid = int(payload["sub"])
        except (ValueError, TypeError):
            return None
        return (
            db.query(Usuario)
            .filter(Usuario.id == uid, Usuario.is_active == True)  # noqa: E712
            .first()
        )
    finally:
        db.close()


def _require_session_or_redirect(request: Request):
    """Devuelve (usuario, None) si hay sesión, o (None, redirect a /auth/login)."""
    usuario = _get_usuario_actual(request)
    if usuario is None:
        return None, RedirectResponse(url="/auth/login", status_code=302)
    return usuario, None


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Página de inicio. Si no hay sesión, redirige a /auth/login."""
    usuario = _get_usuario_actual(request)
    if not usuario:
        return RedirectResponse(url="/auth/login")
    return RedirectResponse(url="/kanban")


@app.get("/kanban", response_class=HTMLResponse)
async def kanban_page(request: Request):
    """Renderiza el tablero Kanban. Requiere sesión activa."""
    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    from app.db.session import SessionLocal
    from app.models.estado import Estado
    from app.models.ticket import Ticket

    db = SessionLocal()
    try:
        estados = db.query(Estado).order_by(Estado.orden.asc()).all()
        tickets_por_estado = {}
        for e in estados:
            tickets_por_estado[e.id] = (
                db.query(Ticket).filter(Ticket.estado_id == e.id)
                .order_by(Ticket.created_at.desc()).all()
            )
        return templates.TemplateResponse(
            "kanban/index.html",
            {
                "request": request, "usuario": usuario,
                "estados": estados, "tickets_por_estado": tickets_por_estado,
            },
        )
    finally:
        db.close()


def _build_tickets_query(
    db,
    q: str = "",
    estado_id: str = "",
    prioridad: str = "",
    asignado_id: str = "",
    archivado: str = "0",
):
    """Construye la query de tickets aplicando los filtros del listado.
    Por defecto muestra solo los tickets activos (archivado=0)."""
    from app.models.ticket import Ticket
    from sqlalchemy import or_

    query = db.query(Ticket)
    # Filtro por texto (título, código o descripción)
    if q:
        patron = f"%{q}%"
        query = query.filter(or_(
            Ticket.codigo.ilike(patron),
            Ticket.titulo.ilike(patron),
            Ticket.descripcion.ilike(patron),
        ))
    # Filtro por estado
    if estado_id:
        try:
            query = query.filter(Ticket.estado_id == int(estado_id))
        except (ValueError, TypeError):
            pass
    # Filtro por prioridad
    if prioridad:
        from app.models.ticket import Prioridad
        try:
            query = query.filter(Ticket.prioridad == Prioridad(prioridad))
        except ValueError:
            pass
    # Filtro por asignado (incluye "sin asignar" cuando asignado_id == -1)
    if asignado_id:
        if asignado_id == "-1":
            query = query.filter(Ticket.asignado_id.is_(None))
        else:
            try:
                query = query.filter(Ticket.asignado_id == int(asignado_id))
            except (ValueError, TypeError):
                pass
    # Filtro por archivado (0=activos, 1=archivados, ""=todos)
    if archivado == "0":
        query = query.filter(Ticket.archivado == False)  # noqa: E712
    elif archivado == "1":
        query = query.filter(Ticket.archivado == True)  # noqa: E712
    # Si archivado == "" (Todos) no aplicamos filtro
    return query


@app.get("/tickets", response_class=HTMLResponse)
async def tickets_page(
    request: Request,
    q: str = "",
    estado_id: str = "",
    prioridad: str = "",
    asignado_id: str = "",
    archivado: str = "0",
):
    """Página de listado de tickets (tabla) con filtros por HTMX.
    Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from app.models.usuario import Usuario
    from app.models.estado import Estado

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        tickets = (
            _build_tickets_query(
                db, q=q, estado_id=estado_id, prioridad=prioridad,
                asignado_id=asignado_id, archivado=archivado,
            )
            .order_by(Ticket.created_at.desc())
            .limit(200)
            .all()
        )
        estados = db.query(Estado).order_by(Estado.orden.asc()).all()
        usuarios = (
            db.query(Usuario)
            .filter(Usuario.is_active == True)  # noqa: E712
            .order_by(Usuario.nombre_completo.asc())
            .all()
        )
        return templates.TemplateResponse(
            "tickets/list.html",
            {
                "request": request, "usuario": usuario, "tickets": tickets,
                "estados": estados, "usuarios": usuarios,
                "q": q, "estado_id": estado_id, "prioridad": prioridad,
                "asignado_id": asignado_id, "archivado": archivado,
            },
        )
    finally:
        db.close()


@app.get("/tickets/tabla", response_class=HTMLResponse)
async def tickets_tabla_partial(
    request: Request,
    q: str = "",
    estado_id: str = "",
    prioridad: str = "",
    asignado_id: str = "",
    archivado: str = "0",
):
    """Partial HTMX: devuelve solo el <tbody> filtrado más un OOB con el
    contador actualizado. Usado por el formulario de filtros del listado.
    Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        tickets = (
            _build_tickets_query(
                db, q=q, estado_id=estado_id, prioridad=prioridad,
                asignado_id=asignado_id, archivado=archivado,
            )
            .order_by(Ticket.created_at.desc())
            .limit(200)
            .all()
        )
        # Renderizamos la misma plantilla y extraemos solo el contenido del <tbody>
        rendered = templates.get_template("tickets/list.html").render(
            request=request, usuario=usuario,
            tickets=tickets, estados=[], usuarios=[],
            q=q, estado_id=estado_id, prioridad=prioridad,
            asignado_id=asignado_id, archivado=archivado,
        )
        # Extraer el <tbody>...</tbody> del HTML renderizado
        import re
        m = re.search(r'<tbody[^>]*id="tickets-tbody"[^>]*>(.*?)</tbody>', rendered, re.DOTALL)
        tbody_inner = m.group(1) if m else ""
        total = len(tickets)
        # OOB: actualizar el contador
        oob_count = (
            f'<p id="tickets-count" hx-swap-oob="true" class="text-sm text-slate-500">'
            f"{total} incidencia(s) encontrada(s)"
            f"</p>"
        )
        return HTMLResponse(content=oob_count + tbody_inner)
    finally:
        db.close()


@app.get("/tickets/nuevo", response_class=HTMLResponse)
async def ticket_nuevo_form(request: Request):
    """Devuelve el fragmento HTML del modal de creación de un nuevo ticket.
    Se carga por HTMX desde el botón '+ Nueva Incidencia' del tablero Kanban.
    Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.catalogo import CatalogoTipo, CatalogoItem
    from app.models.etiqueta import Etiqueta

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        catalogos_tipos = db.query(CatalogoTipo).all()
        catalogos_items = db.query(CatalogoItem).all()
        etiquetas = db.query(Etiqueta).filter(Etiqueta.activo == True).all()  # noqa: E712
        return templates.TemplateResponse(
            "tickets/nuevo_modal.html",
            {
                "request": request,
                "usuario": usuario,
                "catalogos_tipos": catalogos_tipos,
                "catalogos_items": catalogos_items,
                "etiquetas": etiquetas,
            },
        )
    finally:
        db.close()


@app.post("/tickets/crear", response_class=HTMLResponse)
async def ticket_crear(request: Request):
    """Crea un ticket con archivos adjuntos, checklist inicial, fecha de vencimiento,
    descripción en Markdown y devuelve el modal de éxito con un enlace al detalle.
    Requiere sesión activa: el creador es el usuario autenticado."""
    from fastapi import UploadFile, File, Form
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket, TipoIncidencia, Prioridad
    from app.models.estado import Estado
    from app.models.etiqueta import Etiqueta
    from app.models.adjunto import Adjunto
    from app.models.checklist import Checklist
    from app.services.features_service import AdjuntoService, ChecklistService
    from datetime import datetime, timedelta
    from typing import List, Optional

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        # Aceptar tanto form-data como multipart/form-data (para archivos)
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
        else:
            form = await request.form()

        titulo = (form.get("titulo") or "").strip()
        descripcion = (form.get("descripcion") or "").strip()
        tipo = (form.get("tipo") or "incidencia").strip()
        prioridad = (form.get("prioridad") or "media").strip()
        fecha_vencimiento_raw = (form.get("fecha_vencimiento") or "").strip()
        catalogo_tipo_id_raw = form.get("catalogo_tipo_id")
        catalogo_item_id_raw = form.get("catalogo_item_id")
        asignado_id_raw = form.get("asignado_id")
        etiquetas_raw = (form.get("etiquetas") or "").strip()
        checklist_titulo = (form.get("checklist_titulo") or "").strip()
        checklist_items_raw = (form.get("checklist_items") or "").strip()
        descripcion_md_raw = (form.get("descripcion_md") or "false").strip().lower()
        descripcion_md = descripcion_md_raw in ("true", "on", "1", "yes")

        # === Campos extendidos del módulo de Incidencias (LOVs) ===
        modulo = (form.get("modulo") or "").strip() or None
        vista = (form.get("vista") or "").strip() or None
        hu_o_caso_prueba = (form.get("hu_o_caso_prueba") or "").strip() or None
        nota_observacion = (form.get("nota_observacion") or "").strip() or None
        resultado_pruebas = (form.get("resultado_pruebas") or "").strip() or None

        # Validar LOVs (defensivo: el frontend solo envía valores válidos)
        from app.models.ticket import MODULOS_LOV, RESULTADO_PRUEBAS_LOV
        if modulo and modulo not in MODULOS_LOV:
            return HTMLResponse(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Módulo inválido</h3>'
                f'<p class="text-sm text-slate-600 mb-4">El módulo «{modulo}» no está en el catálogo.</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>',
                status_code=400,
            )
        if resultado_pruebas and resultado_pruebas not in RESULTADO_PRUEBAS_LOV:
            return HTMLResponse(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Resultado de pruebas inválido</h3>'
                f'<p class="text-sm text-slate-600 mb-4">El valor «{resultado_pruebas}» no está en el catálogo.</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>',
                status_code=400,
            )

        def _to_int(value, default=None):
            if value is None or str(value).strip() == "":
                return default
            try:
                return int(value)
            except (ValueError, TypeError):
                return default

        asignado_id = _to_int(asignado_id_raw)
        catalogo_tipo_id = _to_int(catalogo_tipo_id_raw)
        catalogo_item_id = _to_int(catalogo_item_id_raw)

        # Validar título obligatorio
        if not titulo:
            return HTMLResponse(
                '''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">
                  <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
                    <h3 class="text-lg font-semibold text-red-700 mb-2">Falta el título</h3>
                    <p class="text-sm text-slate-600 mb-4">Debes ingresar un título para la incidencia.</p>
                    <button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>
                  </div>
                </div>''',
                status_code=400,
            )

        usuario = usuario  # viene de _require_session_or_redirect
        # Asignar al usuario actual si no se especificó
        if not asignado_id:
            asignado_id = usuario.id if usuario else None

        # Estado inicial: el primero con es_inicial=True
        estado_inicial = db.query(Estado).filter(Estado.es_inicial == True).first()  # noqa: E712
        if not estado_inicial:
            estado_inicial = db.query(Estado).order_by(Estado.orden).first()

        # Generar código correlativo
        from sqlalchemy import func
        ultimo = db.query(func.max(Ticket.id)).scalar() or 0
        codigo = f"GRM-INC-2026-{(ultimo + 1):06d}"

        # Mapear tipo y prioridad
        try:
            tipo_enum = TipoIncidencia(tipo)
        except ValueError:
            tipo_enum = TipoIncidencia.INCIDENCIA
        try:
            prioridad_enum = Prioridad(prioridad)
        except ValueError:
            prioridad_enum = Prioridad.MEDIA

        # Parsear fecha de vencimiento (input type="date" => "YYYY-MM-DD")
        fecha_vencimiento_dt = None
        if fecha_vencimiento_raw:
            try:
                fecha_vencimiento_dt = datetime.strptime(fecha_vencimiento_raw, "%Y-%m-%d")
                # Almacenar al final del día
                fecha_vencimiento_dt = fecha_vencimiento_dt.replace(hour=23, minute=59, second=59)
            except ValueError:
                fecha_vencimiento_dt = None

        # Calcular fecha de SLA (la del estado)
        fecha_sla = fecha_vencimiento_dt
        if not fecha_sla and estado_inicial and estado_inicial.sla_horas:
            fecha_sla = datetime.utcnow() + timedelta(hours=estado_inicial.sla_horas)

        ticket = Ticket(
            codigo=codigo,
            titulo=titulo,
            descripcion=descripcion,
            tipo=tipo_enum,
            prioridad=prioridad_enum,
            estado_id=estado_inicial.id if estado_inicial else None,
            creador_id=usuario.id if usuario else None,
            asignado_id=asignado_id,
            catalogo_tipo_id=catalogo_tipo_id,
            fecha_vencimiento_sla=fecha_sla,
            sla_cumplido=-1,
            descripcion_md=descripcion_md,
            # === Campos extendidos del módulo de Incidencias (LOVs) ===
            modulo=modulo,
            vista=vista,
            hu_o_caso_prueba=hu_o_caso_prueba,
            nota_observacion=nota_observacion,
            resultado_pruebas=resultado_pruebas,
        )
        db.add(ticket)
        db.flush()

        # Asignar etiquetas si vienen separadas por coma
        if etiquetas_raw:
            for et_id in [e.strip() for e in etiquetas_raw.split(",") if e.strip()]:
                try:
                    et = db.query(Etiqueta).filter(Etiqueta.id == int(et_id)).first()
                    if et:
                        ticket.etiquetas.append(et)
                except (ValueError, TypeError):
                    pass

        # Procesar archivos adjuntos (drag-and-drop y file picker)
        archivos = form.getlist("archivos") if hasattr(form, "getlist") else []
        archivos_subidos = 0
        errores_adjuntos = []
        for archivo in archivos:
            if not archivo or not getattr(archivo, "filename", None):
                continue
            contenido = await archivo.read()
            if not contenido:
                continue
            adj, error = AdjuntoService(db).guardar_archivo(
                ticket=ticket,
                usuario=usuario,
                file_bytes=contenido,
                nombre_original=archivo.filename,
                mime_type=getattr(archivo, "content_type", None),
                descripcion=None,
            )
            if error:
                errores_adjuntos.append(f"'{archivo.filename}': {error}")
            else:
                archivos_subidos += 1

        # Crear checklist inicial si se proporcionó título y/o items
        checklist_creada = False
        items_creados = 0
        if checklist_titulo or checklist_items_raw:
            titulo_cl = checklist_titulo or "Tareas"
            # Parsear items: una tarea por línea (acepta "- " o no)
            lineas = [
                ln.strip().lstrip("-").strip()
                for ln in checklist_items_raw.splitlines()
                if ln.strip() and ln.strip() != "-"
            ]
            # Si no hay items explícitos pero hay título, creamos la checklist vacía
            cl = ChecklistService(db).crear(
                ticket=ticket,
                titulo=titulo_cl,
                items=[{"texto": t} for t in lineas] if lineas else None,
            )
            checklist_creada = True
            items_creados = len(lineas)

        # Si hay catalogo_item_id, intentar asociarlo vía datos_catalogo
        if catalogo_item_id:
            datos = dict(ticket.datos_catalogo or {})
            datos["catalogo_item_id"] = catalogo_item_id
            ticket.datos_catalogo = datos

        db.commit()
        db.refresh(ticket)

        # Devolver HTML de éxito con enlace al detalle
        # Adjuntar info de los archivos/checklist subidos al trigger
        import json as _json
        trigger_payload = {
            "ticket-created": {
                "ticket_id": ticket.id,
                "codigo": ticket.codigo,
                "archivos_subidos": archivos_subidos,
                "checklist_creada": checklist_creada,
                "items_creados": items_creados,
            }
        }
        return HTMLResponse(
            f'''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="ticket-creado-ok">
              <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 text-center">
                <div class="w-12 h-12 rounded-full bg-emerald-100 mx-auto flex items-center justify-center mb-3">
                  <svg class="w-7 h-7 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                  </svg>
                </div>
                <h3 class="text-lg font-semibold text-slate-800 mb-1">Incidencia creada</h3>
                <p class="text-sm text-slate-500 mb-1">Tu ticket fue registrado con el código</p>
                <p class="font-mono text-base text-indigo-600 font-semibold mb-3">{ticket.codigo}</p>
                {(f'<p class="text-xs text-slate-500 mb-3">{archivos_subidos} archivo(s), {items_creados} item(s) de checklist</p>') if (archivos_subidos or items_creados) else ''}
                {(f'<p class="text-xs text-slate-500 mb-3"><span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">⏱ SLA: vence {ticket.fecha_vencimiento_sla.strftime("%Y-%m-%d %H:%M") if ticket.fecha_vencimiento_sla else "sin fecha"}</span></p>') if ticket.fecha_vencimiento_sla else ''}
                <div class="flex items-center justify-center gap-2">
                  <button data-close-modal
                          hx-get="/api/v1/tickets/{ticket.id}/detalle-html"
                          hx-target="#modal-root" hx-swap="innerHTML"
                          class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
                    Ver detalle
                  </button>
                  <button data-close-modal
                          class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">
                    Cerrar
                  </button>
                </div>
              </div>
            </div>''',
            headers={"HX-Trigger": _json.dumps(trigger_payload)},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.rollback()
        return HTMLResponse(
            f'''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="ticket-creado-error">
              <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
                <h3 class="text-lg font-semibold text-red-700 mb-2">Error al crear la incidencia</h3>
                <p class="text-sm text-slate-600 mb-4">{str(e)}</p>
                <button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>
              </div>
            </div>''',
            status_code=500,
        )
    finally:
        db.close()


@app.get("/catalogos", response_class=HTMLResponse)
async def catalogos_page(request: Request):
    """Página de mantenedores de catálogos. Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.catalogo import CatalogoTipo

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        tipos = db.query(CatalogoTipo).all()
        return templates.TemplateResponse(
            "catalogos/index.html",
            {"request": request, "usuario": usuario, "tipos": tipos},
        )
    finally:
        db.close()


# === Páginas de Autenticación ===
@app.get("/auth/login", response_class=HTMLResponse)
async def auth_login_page(request: Request):
    """Página de inicio de sesión."""
    return templates.TemplateResponse("auth/login.html", {"request": request, "usuario": None})


@app.get("/auth/registro", response_class=HTMLResponse)
async def auth_registro_page(request: Request):
    """Página de registro de nuevos usuarios."""
    return templates.TemplateResponse("auth/registro.html", {"request": request, "usuario": None})


# === Páginas de Gestión de Usuarios (solo Administrador) ===
@app.get("/usuarios", response_class=HTMLResponse)
async def usuarios_index_page(request: Request):
    """Página principal de gestión de usuarios. Solo Administrador.
    Requiere sesión activa; sin sesión redirige a /auth/login."""
    from app.models.usuario import RolUsuario

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return RedirectResponse(url="/kanban")
    return templates.TemplateResponse(
        "usuarios/index.html",
        {"request": request, "usuario": usuario},
    )


# === Página de Roles y Funciones (visible para todos los roles) ===
@app.get("/roles-funciones", response_class=HTMLResponse)
async def roles_funciones_page(request: Request):
    """Matriz de roles y funciones disponibles.

    Muestra una tabla con:
    - Cada rol del sistema y sus funciones habilitadas.
    - La cantidad de usuarios activos en cada rol.
    - Una descripción legible de cada función.

    Visible para cualquier usuario con sesión activa (es una página
    de referencia sobre los permisos del sistema).
    """
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    from sqlalchemy import func

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    # Catálogo de funciones y su descripción legible
    catalogo_funciones = {
        # === Globales (todos los autenticados) ===
        "ver_kanban":       ("Ver tablero Kanban",                          "Consultar las columnas y tarjetas del tablero."),
        "ver_detalle":      ("Ver detalle de incidencia",                   "Abrir el modal con información completa de un ticket."),
        "ver_auditoria":    ("Ver trazabilidad de un ticket",               "Consultar el historial de cambios de un ticket."),
        # === Acciones sobre tickets ===
        "crear_ticket":     ("Crear nueva incidencia",                      "Registrar un nuevo ticket en el sistema."),
        "agregar_comentario":("Agregar comentarios",                         "Comentar en un ticket propio o asignado."),
        "cambiar_estado":   ("Cambiar estado de un ticket",                 "Mover el ticket entre columnas del Kanban."),
        "reasignar":        ("Reasignar ticket a otro agente",              "Cambiar el responsable de un ticket."),
        "editar_ticket":    ("Editar campos de un ticket",                  "Modificar título, descripción, prioridad, etc."),
        "cerrar_ticket":    ("Cerrar / resolver un ticket",                 "Marcar el ticket como cerrado o resuelto."),
        "archivar_ticket":  ("Archivar / restaurar un ticket",              "Mover tickets activos al archivo (soft-delete)."),
        # === Administración ===
        "administrar_usuarios": ("Gestionar usuarios y roles",              "Crear, editar y desactivar cuentas; asignar roles."),
        "administrar_estados":  ("Administrar catálogo de estados",         "Crear, renombrar y asignar responsables a columnas."),
        "administrar_catalogos":("Administrar catálogos dinámicos",         "Gestionar tipos e ítems del catálogo."),
        "administrar_etiquetas":("Administrar etiquetas",                   "Crear, editar y eliminar etiquetas del sistema."),
        "administrar_tableros": ("Administrar tableros y espacios",         "Crear y configurar tableros, espacios y miembros."),
        "importar_exportar":    ("Importar / exportar datos",               "Carga masiva desde CSV y exportación de listados."),
        "ver_dashboard":        ("Ver dashboard de KPIs",                   "Acceder al panel de métricas e indicadores."),
        "configurar_butler":    ("Configurar automatizaciones Butler",      "Crear reglas, botones y comandos programados."),
    }

    # Matriz de permisos por rol (alineada con Usuario.tiene_permiso_para).
    # Usamos listas (no sets) porque Jinja2 no expone el builtin set().
    matriz_permisos = {
        RolUsuario.ADMINISTRADOR: [
            "ver_kanban", "ver_detalle", "ver_auditoria",
            "crear_ticket", "agregar_comentario",
            "cambiar_estado", "reasignar", "editar_ticket", "cerrar_ticket", "archivar_ticket",
            "administrar_usuarios", "administrar_estados", "administrar_catalogos",
            "administrar_etiquetas", "administrar_tableros",
            "importar_exportar", "ver_dashboard", "configurar_butler",
        ],
        RolUsuario.AGENTE_SENIOR: [
            "ver_kanban", "ver_detalle", "ver_auditoria",
            "crear_ticket", "agregar_comentario",
            "cambiar_estado", "reasignar", "editar_ticket", "cerrar_ticket", "archivar_ticket",
            "ver_dashboard",
        ],
        RolUsuario.AGENTE: [
            "ver_kanban", "ver_detalle", "ver_auditoria",
            "crear_ticket", "agregar_comentario",
            "cambiar_estado", "editar_ticket",
        ],
        RolUsuario.SOLICITANTE: [
            "ver_kanban", "ver_detalle", "ver_auditoria",
            "crear_ticket", "agregar_comentario",
        ],
        RolUsuario.OBSERVADOR: [
            "ver_kanban", "ver_detalle", "ver_auditoria",
        ],
    }

    # Conteo de usuarios activos por rol y lista de usuarios por rol
    db = SessionLocal()
    try:
        conteo_por_rol = dict(
            db.query(Usuario.rol, func.count(Usuario.id))
            .filter(Usuario.is_active == True)  # noqa: E712
            .group_by(Usuario.rol)
            .all()
        )
        # Total de usuarios activos
        total_usuarios = db.query(func.count(Usuario.id)).filter(
            Usuario.is_active == True  # noqa: E712
        ).scalar() or 0
        # Orden de visualización (necesario para la query de abajo)
        orden_roles = [
            RolUsuario.ADMINISTRADOR,
            RolUsuario.AGENTE_SENIOR,
            RolUsuario.AGENTE,
            RolUsuario.SOLICITANTE,
            RolUsuario.OBSERVADOR,
        ]
        # Lista de usuarios activos por rol (para mostrarlos en cada bloque)
        usuarios_por_rol = {}
        for rol_enum in orden_roles:
            usuarios_por_rol[rol_enum] = (
                db.query(Usuario)
                .filter(
                    Usuario.rol == rol_enum,
                    Usuario.is_active == True,  # noqa: E712
                )
                .order_by(Usuario.nombre_completo.asc())
                .all()
            )
    finally:
        db.close()

    # Descripciones legibles de los roles
    descripciones_roles = {
        RolUsuario.ADMINISTRADOR: "Control total del sistema. Gestiona usuarios, catálogos, estados y configuración.",
        RolUsuario.AGENTE_SENIOR: "Atiende y resuelve incidencias. Puede cerrar, reasignar y editar cualquier ticket.",
        RolUsuario.AGENTE: "Atiende incidencias. Puede cambiar estado y editar tickets.",
        RolUsuario.SOLICITANTE: "Crea y da seguimiento a sus propias incidencias.",
        RolUsuario.OBSERVADOR: "Solo consulta. No puede crear ni modificar información.",
    }

    return templates.TemplateResponse(
        "roles_funciones/index.html",
        {
            "request": request, "usuario": usuario,
            "matriz_permisos": matriz_permisos,
            "catalogo_funciones": catalogo_funciones,
            "conteo_por_rol": conteo_por_rol,
            "usuarios_por_rol": usuarios_por_rol,
            "total_usuarios": total_usuarios,
            "descripciones_roles": descripciones_roles,
            "orden_roles": orden_roles,
        },
    )


@app.get("/usuarios/tabla", response_class=HTMLResponse)
async def usuarios_tabla_partial(
    request: Request,
    q: str = "",
    rol: str = "",
    activos: str = "1",
):
    """Partial HTMX: tabla de usuarios con filtros. Solo Administrador.
    Requiere sesión activa; sin sesión redirige a /auth/login."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    from sqlalchemy import or_

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Sin permisos</div>')

    db = SessionLocal()
    try:
        query = db.query(Usuario)
        if q:
            patron = f"%{q}%"
            query = query.filter(or_(
                Usuario.username.ilike(patron),
                Usuario.email.ilike(patron),
                Usuario.nombre_completo.ilike(patron),
            ))
        if rol:
            try:
                query = query.filter(Usuario.rol == RolUsuario(rol))
            except ValueError:
                pass
        if activos == "1":
            query = query.filter(Usuario.is_active == True)  # noqa: E712
        usuarios = query.order_by(Usuario.nombre_completo.asc()).all()
        return templates.TemplateResponse(
            "usuarios/tabla.html",
            {"request": request, "usuario": usuario, "usuarios": usuarios},
        )
    finally:
        db.close()


@app.get("/usuarios/nuevo", response_class=HTMLResponse)
async def usuarios_nuevo_modal(request: Request):
    """Modal de creación de nuevo usuario. Solo Administrador.
    Requiere sesión activa; sin sesión redirige a /auth/login."""
    from app.models.usuario import RolUsuario
    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Sin permisos</div>')
    return templates.TemplateResponse(
        "usuarios/form.html",
        {"request": request, "usuario": usuario, "target": None},
    )


@app.get("/usuarios/{usuario_id}/editar", response_class=HTMLResponse)
async def usuarios_editar_modal(request: Request, usuario_id: int):
    """Modal de edición de usuario. Solo Administrador.
    Requiere sesión activa; sin sesión redirige a /auth/login."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    usuario_actual, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
    if usuario_actual.rol != RolUsuario.ADMINISTRADOR:
        return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Sin permisos</div>')
    db = SessionLocal()
    try:
        target = db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not target:
            return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Usuario no encontrado</div>')
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": usuario_actual, "target": target},
        )
    finally:
        db.close()


# === Página de Importar / Exportar (solo Administrador) ===
@app.get("/importar-exportar", response_class=HTMLResponse)
async def importar_exportar_page(request: Request):
    """Página con herramientas de import/export. Solo Administrador.
    Requiere sesión activa; sin sesión redirige a /auth/login."""
    from app.db.session import SessionLocal
    from app.models.estado import Estado
    from app.models.etiqueta import Etiqueta

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
    from app.models.usuario import RolUsuario
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return RedirectResponse(url="/kanban")
    db = SessionLocal()
    try:
        estados = db.query(Estado).order_by(Estado.orden).all()
        etiquetas = db.query(Etiqueta).filter(Etiqueta.activo == True).all()  # noqa: E712
        return templates.TemplateResponse(
            "importar_exportar/index.html",
            {"request": request, "usuario": usuario, "estados": estados, "etiquetas": etiquetas},
        )
    finally:
        db.close()


# === Endpoint de exportación CSV desde /tickets (compatibilidad) ===
@app.get("/tickets/exportar-csv", response_class=HTMLResponse)
async def tickets_exportar_csv(request: Request):
    """Redirige a la exportación CSV del módulo de import/export."""
    return RedirectResponse(url="/api/v1/tickets-ie/exportar/csv")


# === Páginas de Workspaces / Tableros / Vistas / Butler / Notificaciones ===
# ELIMINADO: _usuario_demo(db) ya no existe. Era un fallback inseguro que
# devolvía automáticamente el primer usuario administrador como sesión
# activa cuando no había cookie. Todas las páginas ahora exigen sesión
# real mediante _require_session_or_redirect.


@app.get("/espacios", response_class=HTMLResponse)
async def espacios_page(request: Request):
    """Lista de espacios de trabajo (workspaces). Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.espacio import Espacio
    from app.models.espacio import espacio_miembros, Tablero
    from sqlalchemy import func

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        espacios = db.query(Espacio).order_by(Espacio.created_at.desc()).all()
        # Anotar totales (atributos transient, no las properties read-only)
        for e in espacios:
            e._total_tableros = db.query(func.count(Tablero.id)).filter(Tablero.espacio_id == e.id).scalar() or 0
            e._total_miembros = db.query(func.count(espacio_miembros.c.usuario_id)).filter(espacio_miembros.c.espacio_id == e.id).scalar() or 0
        return templates.TemplateResponse(
            "espacios/index.html",
            {"request": request, "usuario": usuario, "espacios": espacios},
        )
    finally:
        db.close()


@app.get("/tableros", response_class=HTMLResponse)
async def tableros_page(request: Request):
    """Lista de tableros (filtrable por espacio). Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.espacio import Espacio, Tablero
    from app.models.ticket import Ticket
    from app.models.estado import Estado
    from sqlalchemy import func

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    espacio_id = request.query_params.get("espacio")

    db = SessionLocal()
    try:
        espacios = db.query(Espacio).order_by(Espacio.nombre).all()
        espacio_actual = None
        if espacio_id:
            try:
                espacio_actual = db.query(Espacio).filter(Espacio.id == int(espacio_id)).first()
            except (ValueError, TypeError):
                pass
        q = db.query(Tablero)
        if espacio_actual:
            q = q.filter(Tablero.espacio_id == espacio_actual.id)
        tableros = q.order_by(Tablero.created_at.desc()).all()
        for t in tableros:
            t.total_tickets = db.query(func.count(Ticket.id)).filter(
                Ticket.estado_id.in_(
                    db.query(Estado.id).filter(Estado.tablero_id == t.id)
                )
            ).scalar() or 0
            t.total_listas = db.query(func.count(Estado.id)).filter(Estado.tablero_id == t.id).scalar() or 0
        return templates.TemplateResponse(
            "tableros/index.html",
            {
                "request": request, "usuario": usuario,
                "tableros": tableros, "espacios": espacios, "espacio_actual": espacio_actual,
            },
        )
    finally:
        db.close()


@app.get("/vistas/tabla", response_class=HTMLResponse)
async def vista_tabla_page(request: Request):
    """Vista multidimensional: Tabla. Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from app.models.estado import Estado
    from app.models.usuario import Usuario
    from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
    from app.models.etiqueta import Etiqueta
    from app.models.espacio import Espacio

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    espacio_id = request.query_params.get("espacio")
    db = SessionLocal()
    try:
        # Si hay espacio, filtrar; si no, mostrar todos
        q = db.query(Ticket).filter(Ticket.archivado == False)  # noqa: E712
        if espacio_id:
            try:
                from app.models.espacio import Tablero
                tableros_esp = db.query(Tablero.id).filter(Tablero.espacio_id == int(espacio_id)).all()
                ids = [t[0] for t in tableros_esp]
                if ids:
                    q = q.filter(Ticket.tablero_id.in_(ids))
                else:
                    q = q.filter(Ticket.id.is_(None))
            except (ValueError, TypeError):
                pass
        tickets = q.order_by(Ticket.created_at.desc()).limit(200).all()
        estados = db.query(Estado).order_by(Estado.orden).all()
        usuarios = db.query(Usuario).order_by(Usuario.nombre_completo).all()
        # Custom fields (del primer tablero disponible, o globales)
        custom_fields = db.query(CampoPersonalizado).order_by(CampoPersonalizado.posicion).limit(10).all()
        filas = []
        for t in tickets:
            f = {
                "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                "estado": t.estado.nombre if t.estado else "",
                "estado_color": t.estado.color if t.estado else "#94a3b8",
                "prioridad": t.prioridad.value if t.prioridad else "media",
                "asignado": t.asignado.nombre_completo if t.asignado else None,
                "asignado_id": t.asignado_id,
                "fecha_inicio": t.fecha_inicio.strftime("%Y-%m-%d") if t.fecha_inicio else None,
                "fecha_vencimiento": t.fecha_vencimiento_sla.strftime("%Y-%m-%d") if t.fecha_vencimiento_sla else None,
                "sla": t.estado_sla_visual,
                "etiquetas": [{"nombre": e.nombre, "color": e.color} for e in t.etiquetas] if t.etiquetas else [],
            }
            # Valores de custom fields
            for c in custom_fields:
                vc = db.query(ValorCampo).filter(
                    ValorCampo.campo_id == c.id, ValorCampo.ticket_id == t.id
                ).first()
                f[f"custom_{c.id}"] = str(vc.valor) if vc and vc.valor else None
            filas.append(f)
        return templates.TemplateResponse(
            "vistas/tabla.html",
            {
                "request": request, "usuario": usuario, "filas": filas,
                "estados": estados, "usuarios": usuarios, "custom_fields": custom_fields,
                "espacio_id": espacio_id,
            },
        )
    finally:
        db.close()


@app.get("/vistas/calendario", response_class=HTMLResponse)
async def vista_calendario_page(request: Request):
    """Vista multidimensional: Calendario. Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    espacio_id = request.query_params.get("espacio")
    db = SessionLocal()
    try:
        q = db.query(Ticket).filter(Ticket.archivado == False)  # noqa: E712
        if espacio_id:
            try:
                from app.models.espacio import Tablero
                tableros_esp = db.query(Tablero.id).filter(Tablero.espacio_id == int(espacio_id)).all()
                ids = [t[0] for t in tableros_esp]
                if ids:
                    q = q.filter(Ticket.tablero_id.in_(ids))
            except (ValueError, TypeError):
                pass
        tickets = q.filter(Ticket.fecha_vencimiento_sla.isnot(None)).limit(500).all()
        tickets_cal = []
        for t in tickets:
            f = t.fecha_vencimiento_sla.strftime("%Y-%m-%d")
            tickets_cal.append({
                "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                "fecha": f, "prioridad": t.prioridad.value if t.prioridad else "media",
            })
            if t.fecha_inicio:
                tickets_cal.append({
                    "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                    "fecha": t.fecha_inicio.strftime("%Y-%m-%d"),
                    "prioridad": t.prioridad.value if t.prioridad else "media",
                })
        return templates.TemplateResponse(
            "vistas/calendario.html",
            {"request": request, "usuario": usuario, "tickets_cal": tickets_cal, "espacio_id": espacio_id},
        )
    finally:
        db.close()


@app.get("/vistas/timeline", response_class=HTMLResponse)
async def vista_timeline_page(request: Request):
    """Vista multidimensional: Timeline (Gantt simple). Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from datetime import datetime

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    espacio_id = request.query_params.get("espacio")
    db = SessionLocal()
    try:
        q = db.query(Ticket).filter(
            Ticket.archivado == False,  # noqa: E712
            Ticket.fecha_inicio.isnot(None),
            Ticket.fecha_vencimiento_sla.isnot(None),
        )
        if espacio_id:
            try:
                from app.models.espacio import Tablero
                tableros_esp = db.query(Tablero.id).filter(Tablero.espacio_id == int(espacio_id)).all()
                ids = [t[0] for t in tableros_esp]
                if ids:
                    q = q.filter(Ticket.tablero_id.in_(ids))
            except (ValueError, TypeError):
                pass
        tickets = q.order_by(Ticket.fecha_inicio.asc()).limit(100).all()
        tickets_tl = []
        for t in tickets:
            inicio = t.fecha_inicio
            fin = t.fecha_vencimiento_sla
            hoy = datetime.utcnow()
            if fin > inicio:
                total = (fin - inicio).days or 1
                if hoy < inicio:
                    prog = 0
                elif hoy > fin:
                    prog = 100
                else:
                    prog = int(((hoy - inicio).days / total) * 100)
            else:
                prog = 100 if t.sla_cumplido == 1 else 0
            tickets_tl.append({
                "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                "prioridad": t.prioridad.value if t.prioridad else "media",
                "estado": t.estado.nombre if t.estado else "",
                "asignado": t.asignado.nombre_completo if t.asignado else None,
                "fecha_inicio": inicio.strftime("%Y-%m-%d"),
                "fecha_fin": fin.strftime("%Y-%m-%d"),
                "duracion_dias": max(1, (fin - inicio).days),
                "progreso": prog, "estado_sla": t.estado_sla_visual,
            })
        return templates.TemplateResponse(
            "vistas/timeline.html",
            {"request": request, "usuario": usuario, "tickets_timeline": tickets_tl, "espacio_id": espacio_id},
        )
    finally:
        db.close()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Dashboard con KPIs y métricas del módulo de incidencias.
    Requiere sesión activa."""
    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
    return templates.TemplateResponse(
        "dashboard/index.html",
        {"request": request, "usuario": usuario},
    )


@app.get("/butler", response_class=HTMLResponse)
async def butler_page(request: Request):
    """Página de automatizaciones Butler. Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.automacion import ReglaAutomatizacion
    from app.models.butler_extras import BotonTarjeta, ComandoProgramado

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        reglas = db.query(ReglaAutomatizacion).order_by(ReglaAutomatizacion.nombre).all()
        botones = db.query(BotonTarjeta).order_by(BotonTarjeta.posicion).all()
        comandos = db.query(ComandoProgramado).order_by(ComandoProgramado.nombre).all()
        return templates.TemplateResponse(
            "butler/index.html",
            {
                "request": request, "usuario": usuario,
                "reglas": reglas, "botones": botones, "comandos": comandos,
            },
        )
    finally:
        db.close()


@app.get("/notificaciones", response_class=HTMLResponse)
async def notificaciones_page(request: Request):
    """Centro de notificaciones del usuario. Requiere sesión activa."""
    from app.db.session import SessionLocal
    from app.models.watch import Notificacion

    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect

    db = SessionLocal()
    try:
        notifs = db.query(Notificacion).filter(
            Notificacion.usuario_id == usuario.id
        ).order_by(Notificacion.created_at.desc()).limit(100).all()
        # Anotar origen_usuario como string
        for n in notifs:
            n.origen_usuario = n.origen_usuario_id if n.origen_usuario_id else None
        return templates.TemplateResponse(
            "notificaciones/index.html",
            {"request": request, "usuario": usuario, "notificaciones": notifs},
        )
    finally:
        db.close()


# === Vista pública de tablero (compartida por /p/{slug}) ===
@app.get("/p/{slug}", response_class=HTMLResponse)
async def tablero_publico(slug: str, request: Request):
    """Vista pública (sin auth) de un tablero con visibilidad=publico."""
    from app.db.session import SessionLocal
    from app.models.espacio import Tablero, Estado
    from app.models.ticket import Ticket
    from sqlalchemy import func
    from fastapi import HTTPException
    db = SessionLocal()
    try:
        tablero = db.query(Tablero).filter(
            Tablero.slug_publico == slug,
            Tablero.visibilidad == "publico",
        ).first()
        if not tablero:
            raise HTTPException(status_code=404, detail="Tablero no encontrado o no es público")
        estados = db.query(Estado).filter(Estado.tablero_id == tablero.id).order_by(Estado.orden).all()
        # Anotar tickets por estado
        for e in estados:
            e.tickets_list = db.query(Ticket).filter(
                Ticket.estado_id == e.id, Ticket.archivado == False  # noqa: E712
            ).order_by(Ticket.created_at.desc()).all()
        return templates.TemplateResponse(
            "tableros/publico.html",
            {
                "request": request, "tablero": tablero, "estados": estados,
                "slug": slug,
            },
        )
    finally:
        db.close()


# === Health check robusto (usado por Railway y por balanceadores) ===
@app.get("/health")
def health():
    """Verifica estado del servicio: app, BD y Redis."""
    status = {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": "unknown",
        "redis": "unknown",
    }
    http_code = 200

    # 1) Verificar base de datos
    try:
        from sqlalchemy import text
        from app.db.session import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {e}"
        status["status"] = "degraded"
        http_code = 503

    # 2) Verificar Redis (si está configurado y disponible)
    try:
        import redis
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        if client.ping():
            status["redis"] = "ok"
        else:
            status["redis"] = "error: ping returned false"
            status["status"] = "degraded"
            http_code = 503
    except Exception as e:
        # Redis puede no estar en modo demo; no marcamos como crítico
        status["redis"] = f"unavailable: {e}"

    return JSONResponse(status, status_code=http_code)


@app.get("/ready")
def ready():
    """Readiness check: solo indica que el proceso arrancó (no valida deps)."""
    return {"status": "ready", "app": settings.APP_NAME}


@app.get("/info")
def info():
    """Información del entorno (útil para debugging)."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "debug": settings.DEBUG,
        "port": int(os.getenv("PORT", "8000")),
        "database_url": (settings.get_database_url().split("@")[-1]
                         if "@" in settings.get_database_url()
                         else "sqlite"),
        "redis_configured": bool(settings.REDIS_URL),
        "celery_broker_configured": bool(settings.CELERY_BROKER_URL),
    }


# === Compresión estática en producción ===
# WhiteNoise 6.x expone una clase WSGI (no ASGI middleware). Para integrarla
# con FastAPI/ASGI necesitaríamos un adaptador (a2wsgi). Por simplicidad
# y robustez usamos `StaticFiles` de FastAPI (que es nativo ASGI) y
# dejamos WhiteNoise instalado solo como referencia para el entorno WSGI
# (gunicorn lo podría usar si se importa vía `wsgi.py`).
#
# Activar WhiteNoise solo si el adaptador ASGI está disponible
# (a2wsgi) Y no estamos en debug. De lo contrario, StaticFiles hace
# el trabajo perfectamente.
if HAS_WHITENOISE and not settings.DEBUG:
    try:
        from a2wsgi import ASGIMiddleware  # type: ignore
        app = ASGIMiddleware(app)
        logger.info("a2wsgi+WhiteNoise ASGIMiddleware activado")
    except ImportError:
        # Sin a2wsgi no podemos integrar WhiteNoise con ASGI; StaticFiles
        # sigue siendo válido.
        logger.info(
            "WhiteNoise instalado pero a2wsgi no disponible; "
            "sirviendo /static con StaticFiles de FastAPI"
        )
