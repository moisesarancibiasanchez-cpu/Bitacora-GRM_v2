"""
Router principal v1: agrupa todos los endpoints.
"""
from fastapi import APIRouter
from app.api.v1 import tickets, estados, catalogos, kanban


api_router = APIRouter()
api_router.include_router(tickets.router)
api_router.include_router(estados.router)
api_router.include_router(catalogos.router)
api_router.include_router(kanban.router)
