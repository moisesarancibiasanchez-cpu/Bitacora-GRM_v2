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
