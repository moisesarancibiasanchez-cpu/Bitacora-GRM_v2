"""
Aplicación principal FastAPI - Bitácora GRM.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.router import api_router
from app.core.config import settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización al arranque (crear tablas si no existen)."""
    if settings.DEBUG:
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

# === Archivos estáticos ===
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

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


@app.get("/health")
def health():
    """Health-check del sistema."""
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
