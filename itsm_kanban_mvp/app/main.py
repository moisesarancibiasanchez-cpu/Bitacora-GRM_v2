"""FastAPI application entrypoint."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.api.v1 import auth as auth_router
from app.api.v1 import kanban as kanban_router
from app.api.v1 import tickets as tickets_router
from app.api.v1 import catalogos as catalogos_router
from app.db.init_db import init_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la BD y siembra datos al arrancar."""
    try:
        init_all()
    except Exception as exc:
        logger.exception("Error en init_all(): %s", exc)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# Static files (CSS, JS)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(auth_router.router)
app.include_router(kanban_router.router)
app.include_router(tickets_router.router)
app.include_router(catalogos_router.router)


templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/kanban", status_code=303)


@app.get("/health", response_class=HTMLResponse)
def health():
    return HTMLResponse(content="OK", status_code=200)


@app.get("/salud", response_class=HTMLResponse)
def salud():
    return HTMLResponse(content='{"status":"ok","app":"' + settings.app_name + '"}', media_type="application/json")
