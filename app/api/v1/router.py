"""
Router principal v1: agrupa todos los endpoints.
"""
from fastapi import APIRouter
from app.api.v1 import tickets, estados, catalogos, kanban, features
from app.api.v1 import trello_features, metricas, buscar, butler
from app.api.v1 import auth, usuarios, import_export, dev_inbox, admin_uat
from app.api.v1 import migraciones
# === FEATURE 3 — Dependencias Gantt + import .mpp/XML ===
from app.api.v1 import dependencias
# === FEATURE 4 — Etapas de proyecto UAT (sub-bars en Gantt) ===
from app.api.v1 import etapas
# === FEATURE 5 — Referencias internas entre tickets (issue links) ===
from app.api.v1 import referencias
# === Sistema de Backups de Base de Datos ===
from app.api.v1 import backups


api_router = APIRouter()
# ==============================================================================
# ORDEN DE REGISTRO DE ROUTERS — IMPORTANTE
# ==============================================================================
# FastAPI/Starlette matchea rutas en ORDEN DE REGISTRO. Las rutas más
# específicas (path fijo, sin parámetros) DEBEN registrarse ANTES que las
# rutas con path-parameter para evitar "shadowing".
#
# Bug histórico: ``GET /api/v1/tickets/buscar`` (FEATURE 5 — Referencias)
# quedaba shadowed por ``GET /api/v1/tickets/{ticket_id}`` del tickets
# router, devolviendo 422 ("buscar" no es int) y disparando el toast
# genérico "Error al guardar el cambio" en el frontend.
#
# Solución aplicada: registrar ``referencias.router_tickets`` (que contiene
# la ruta literal ``/buscar``) ANTES que ``tickets.router``.
# Las rutas ``/{ticket_id}/referencias`` y ``/{ticket_id}/referencias/resumen``
# del mismo router son más específicas (un segmento extra) que
# ``/{ticket_id}`` del tickets router, por lo que no entran en conflicto.
api_router.include_router(referencias.router_tickets)
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
api_router.include_router(dev_inbox.router)
api_router.include_router(admin_uat.router)
api_router.include_router(migraciones.router)
# === FEATURE 3 — Dependencias Gantt ===
api_router.include_router(dependencias.router)
# === FEATURE 4 — Etapas de proyecto ===
api_router.include_router(etapas.router)
# === FEATURE 5 — Referencias internas (router secundario, sin shadowing) ===
api_router.include_router(referencias.router)
# === Sistema de Backups de Base de Datos ===
api_router.include_router(backups.router)
