"""
WSGI / ASGI entry point - Bitácora GRM
Usado por gunicorn con worker_class=uvicorn.workers.UvicornWorker.
"""
from app.main import app  # re-exporta la instancia de FastAPI

__all__ = ["app"]
