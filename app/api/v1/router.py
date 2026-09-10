"""
Router principal v1: agrupa todos los endpoints.
"""
from fastapi import APIRouter
from app.api.v1 import tickets, estados, catalogos, kanban, features
from app.api.v1 import trello_features, metricas, buscar, butler
from app.api.v1 import auth, usuarios, import_export


api_router = APIRouter()
api_router.include_router(tickets.router)
api_router.include_router(estados.router)
api_router.include_router(catalogos.router)
api_router.include_router(kanban.router)
api_router.include_router(features.router)
api_router.include_router(trello_features.router)
api_router.include_router(metricas.router)
api_router.include_router(buscar.router)
api_router.include_router(butler.router)
api_router.include_router(auth.router)
api_router.include_router(usuarios.router)
api_router.include_router(import_export.router)
