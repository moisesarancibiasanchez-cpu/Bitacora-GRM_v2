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
    """Resuelve el usuario actual desde cookie/JWT o el primer admin (modo demo)."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    from app.core.security import decode_access_token
    db = SessionLocal()
    try:
        # 1) Cookie
        token = request.cookies.get("access_token")
        if token:
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                try:
                    uid = int(payload["sub"])
                    u = db.query(Usuario).filter(
                        Usuario.id == uid, Usuario.is_active == True  # noqa: E712
                    ).first()
                    if u:
                        return u
                except (ValueError, TypeError):
                    pass
        # 2) Modo demo: primer admin
        u = db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
        if not u:
            u = db.query(Usuario).first()
        return u
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Página de inicio. Si no hay sesión, redirige a /auth/login."""
    usuario = _get_usuario_actual(request)
    if not usuario:
        return RedirectResponse(url="/auth/login")
    return RedirectResponse(url="/kanban")


@app.get("/kanban", response_class=HTMLResponse)
async def kanban_page(request: Request):
    """Renderiza el tablero Kanban (versión demo, sin auth para visualización)."""
    from app.db.session import SessionLocal
    from app.models.estado import Estado
    from app.models.ticket import Ticket
    from app.models.usuario import Usuario, RolUsuario

    db = SessionLocal()
    try:
        # En modo demo, tomamos el primer administrador como "usuario actual"
        usuario = db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
        if not usuario:
            usuario = db.query(Usuario).first()
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
    """Página de listado de tickets (tabla) con filtros por HTMX."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from app.models.usuario import Usuario, RolUsuario
    from app.models.estado import Estado

    db = SessionLocal()
    try:
        usuario = (
            db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
            or db.query(Usuario).first()
        )
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
    contador actualizado. Usado por el formulario de filtros del listado."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket

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
            request=request, usuario=request.state.usuario if hasattr(request.state, "usuario") else None,
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
    Se carga por HTMX desde el botón '+ Nueva Incidencia' del tablero Kanban."""
    from app.db.session import SessionLocal
    from app.models.catalogo import CatalogoTipo, CatalogoItem
    from app.models.usuario import Usuario, RolUsuario
    from app.models.etiqueta import Etiqueta

    db = SessionLocal()
    try:
        usuario = (
            db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
            or db.query(Usuario).first()
        )
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
    descripción en Markdown y devuelve el modal de éxito con un enlace al detalle."""
    from fastapi import UploadFile, File, Form
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket, TipoIncidencia, Prioridad
    from app.models.usuario import Usuario
    from app.models.estado import Estado
    from app.models.etiqueta import Etiqueta
    from app.models.adjunto import Adjunto
    from app.models.checklist import Checklist
    from app.services.features_service import AdjuntoService, ChecklistService
    from datetime import datetime, timedelta
    from typing import List, Optional

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

        usuario = (
            db.query(Usuario).filter(Usuario.rol == "administrador").first()
            or db.query(Usuario).first()
        )
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
    """Página de mantenedores de catálogos."""
    from app.db.session import SessionLocal
    from app.models.catalogo import CatalogoTipo
    from app.models.usuario import Usuario, RolUsuario

    db = SessionLocal()
    try:
        usuario = db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first() \
                or db.query(Usuario).first()
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
    """Página principal de gestión de usuarios. Solo Administrador."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario

    db = SessionLocal()
    try:
        usuario = _get_usuario_actual(request)
        if not usuario or usuario.rol != RolUsuario.ADMINISTRADOR:
            return RedirectResponse(url="/kanban")
        return templates.TemplateResponse(
            "usuarios/index.html",
            {"request": request, "usuario": usuario},
        )
    finally:
        db.close()


@app.get("/usuarios/tabla", response_class=HTMLResponse)
async def usuarios_tabla_partial(
    request: Request,
    q: str = "",
    rol: str = "",
    activos: str = "1",
):
    """Partial HTMX: tabla de usuarios con filtros. Solo Administrador."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    from sqlalchemy import or_

    db = SessionLocal()
    try:
        usuario = _get_usuario_actual(request)
        if not usuario or usuario.rol != RolUsuario.ADMINISTRADOR:
            return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Sin permisos</div>')

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
    """Modal de creación de nuevo usuario. Solo Administrador."""
    from app.models.usuario import RolUsuario
    usuario = _get_usuario_actual(request)
    if not usuario or usuario.rol != RolUsuario.ADMINISTRADOR:
        return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Sin permisos</div>')
    return templates.TemplateResponse(
        "usuarios/form.html",
        {"request": request, "usuario": usuario, "target": None},
    )


@app.get("/usuarios/{usuario_id}/editar", response_class=HTMLResponse)
async def usuarios_editar_modal(request: Request, usuario_id: int):
    """Modal de edición de usuario. Solo Administrador."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    db = SessionLocal()
    try:
        usuario_actual = _get_usuario_actual(request)
        if not usuario_actual or usuario_actual.rol != RolUsuario.ADMINISTRADOR:
            return HTMLResponse('<div class="p-6 text-center text-red-600 text-sm">Sin permisos</div>')
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
    """Página con herramientas de import/export. Solo Administrador."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario
    from app.models.estado import Estado
    from app.models.etiqueta import Etiqueta

    db = SessionLocal()
    try:
        usuario = _get_usuario_actual(request)
        if not usuario or usuario.rol != RolUsuario.ADMINISTRADOR:
            return RedirectResponse(url="/kanban")
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
def _usuario_demo(db):
    from app.models.usuario import Usuario, RolUsuario
    return (
        db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
        or db.query(Usuario).first()
    )


@app.get("/espacios", response_class=HTMLResponse)
async def espacios_page(request: Request):
    """Lista de espacios de trabajo (workspaces)."""
    from app.db.session import SessionLocal
    from app.models.espacio import Espacio
    from app.models.espacio import espacio_miembros, Tablero
    from sqlalchemy import func

    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
    """Lista de tableros (filtrable por espacio)."""
    from app.db.session import SessionLocal
    from app.models.espacio import Espacio, Tablero
    from app.models.ticket import Ticket
    from app.models.estado import Estado
    from sqlalchemy import func

    espacio_id = request.query_params.get("espacio")

    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
    """Vista multidimensional: Tabla."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from app.models.estado import Estado
    from app.models.usuario import Usuario
    from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
    from app.models.etiqueta import Etiqueta
    from app.models.espacio import Espacio
    espacio_id = request.query_params.get("espacio")
    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
    """Vista multidimensional: Calendario."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    espacio_id = request.query_params.get("espacio")
    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
    """Vista multidimensional: Timeline (Gantt simple)."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from datetime import datetime
    espacio_id = request.query_params.get("espacio")
    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
    """Dashboard con KPIs y métricas del módulo de incidencias."""
    from app.db.session import SessionLocal
    from app.models.usuario import Usuario, RolUsuario

    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
        return templates.TemplateResponse(
            "dashboard/index.html",
            {"request": request, "usuario": usuario},
        )
    finally:
        db.close()


@app.get("/butler", response_class=HTMLResponse)
async def butler_page(request: Request):
    """Página de automatizaciones Butler."""
    from app.db.session import SessionLocal
    from app.models.automacion import ReglaAutomatizacion
    from app.models.butler_extras import BotonTarjeta, ComandoProgramado
    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
    """Centro de notificaciones del usuario."""
    from app.db.session import SessionLocal
    from app.models.watch import Notificacion
    db = SessionLocal()
    try:
        usuario = _usuario_demo(db)
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
