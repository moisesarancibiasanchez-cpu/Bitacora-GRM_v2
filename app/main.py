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
    """Inicialización al arranque (crear tablas si no existen)."""
    if settings.DEBUG or os.getenv("AUTO_INIT_DB", "false").lower() == "true":
        try:
            from app.db.init_db import init_database
            init_database()
        except Exception as e:
            logger.warning(f"No se pudo inicializar la BD automáticamente: {e}")
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


# === Routers API ===
app.include_router(api_router, prefix="/api/v1")


# === Rutas de páginas (HTML server-rendered) ===
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Página de inicio, redirige al tablero Kanban."""
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


@app.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request):
    """Página de listado de tickets (tabla)."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket
    from app.models.usuario import Usuario, RolUsuario

    db = SessionLocal()
    try:
        usuario = db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first() \
                or db.query(Usuario).first()
        tickets = db.query(Ticket).order_by(Ticket.created_at.desc()).limit(50).all()
        return templates.TemplateResponse(
            "tickets/list.html",
            {"request": request, "usuario": usuario, "tickets": tickets},
        )
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
async def ticket_crear(
    request: Request,
    titulo: str = "",
    descripcion: str = "",
    tipo: str = "incidencia",
    prioridad: str = "media",
    asignado_id: int | None = None,
    catalogo_tipo_id: int | None = None,
    catalogo_item_id: int | None = None,
    etiquetas: str = "",
):
    """Crea un ticket y devuelve el modal de éxito con un enlace al detalle."""
    from app.db.session import SessionLocal
    from app.models.ticket import Ticket, TipoIncidencia, Prioridad
    from app.models.usuario import Usuario
    from app.models.estado import Estado
    from app.models.etiqueta import Etiqueta
    from datetime import datetime, timedelta

    db = SessionLocal()
    try:
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

        # Calcular fecha de SLA
        fecha_sla = None
        if estado_inicial and estado_inicial.sla_horas:
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
        )
        db.add(ticket)
        db.flush()

        # Asignar etiquetas si vienen separadas por coma
        if etiquetas:
            for et_id in [e.strip() for e in etiquetas.split(",") if e.strip()]:
                try:
                    et = db.query(Etiqueta).filter(Etiqueta.id == int(et_id)).first()
                    if et:
                        ticket.etiquetas.append(et)
                except (ValueError, TypeError):
                    pass

        db.commit()
        db.refresh(ticket)

        # Devolver HTML de éxito con enlace al detalle
        return HTMLResponse(
            f'''<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 modal-backdrop">
              <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 text-center">
                <div class="w-12 h-12 rounded-full bg-emerald-100 mx-auto flex items-center justify-center mb-3">
                  <svg class="w-7 h-7 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                  </svg>
                </div>
                <h3 class="text-lg font-semibold text-slate-800 mb-1">Incidencia creada</h3>
                <p class="text-sm text-slate-500 mb-1">Tu ticket fue registrado con el código</p>
                <p class="font-mono text-base text-indigo-600 font-semibold mb-4">{ticket.codigo}</p>
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
            headers={"HX-Trigger": "ticket-created"},
        )
    except Exception as e:
        db.rollback()
        return HTMLResponse(
            f'''<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 modal-backdrop">
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
