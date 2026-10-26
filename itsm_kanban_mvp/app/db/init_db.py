"""Inicialización de la base de datos: crea tablas y siembra datos mínimos.

Uso:
    python -m app.db.init_db
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine

# Importar todos los modelos para que Base.metadata los registre
import app.models  # noqa: F401
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado, CategoriaEstado
from app.models.transicion import Transicion, RolRequerido
from app.models.sla import SLAPolitica
from app.models.catalogo import CatalogoItem, TipoCatalogo
from app.models.ticket import PrioridadTicket
from app.models.auditoria import AuditoriaEvento

logger = logging.getLogger(__name__)


def _crear_tablas() -> None:
    logger.info("Creando tablas (si no existen) en %s", settings.database_url.split("@")[-1])
    Base.metadata.create_all(bind=engine)


def _seed_admin(db) -> None:
    if db.execute(select(Usuario).where(Usuario.username == settings.bootstrap_admin_username)).scalar_one_or_none():
        logger.info("Admin «%s» ya existe. Omitiendo seed.", settings.bootstrap_admin_username)
        return
    admin = Usuario(
        username=settings.bootstrap_admin_username,
        email=settings.bootstrap_admin_email,
        nombre_completo="Administrador Inicial",
        password_hash=hash_password(settings.bootstrap_admin_password),
        rol=RolUsuario.ADMINISTRADOR,
        activo=True,
    )
    db.add(admin)
    db.commit()
    logger.info("Admin «%s» creado (contraseña: ver .env).", settings.bootstrap_admin_username)


def _seed_estados(db) -> None:
    """Estados seed: Pendiente, En curso, Bloqueado, En revisión, Cerrado, Cancelado."""
    if db.query(Estado).count() > 0:
        logger.info("Estados ya sembrados. Omitiendo.")
        return
    estados_seed = [
        # (nombre, orden, categoria, color, es_inicial, es_final)
        ("Pendiente",     1, CategoriaEstado.PENDIENTE,    "#64748b", True,  False),
        ("En curso",      2, CategoriaEstado.EN_PROGRESO,  "#2563eb", False, False),
        ("Bloqueado",     3, CategoriaEstado.BLOQUEADO,    "#ea580c", False, False),
        ("En revisión",   4, CategoriaEstado.EN_PROGRESO,  "#9333ea", False, False),
        ("Cerrado",       5, CategoriaEstado.CERRADO,      "#16a34a", False, True),
        ("Cancelado",     6, CategoriaEstado.CANCELADO,    "#9ca3af", False, True),
    ]
    for nombre, orden, cat, color, ini, fin in estados_seed:
        db.add(Estado(
            nombre=nombre, descripcion=f"Estado «{nombre}»",
            orden=orden, categoria=cat, color=color,
            es_inicial=ini, es_final=fin, activo=True,
        ))
    db.commit()
    logger.info("Sembrados %d estados.", len(estados_seed))


def _seed_transiciones(db) -> None:
    """Reglas de transición: definen qué movimientos son legales en el Kanban."""
    if db.query(Transicion).count() > 0:
        logger.info("Transiciones ya sembradas. Omitiendo.")
        return
    estados = {e.nombre: e for e in db.query(Estado).all()}

    reglas = [
        # (origen, destino, rol_requerido, requiere_comentario, nombre, descripcion)
        ("Pendiente",  "En curso",    RolRequerido.AGENTE,        False, "Iniciar",       "Pasar de Pendiente a En curso"),
        ("Pendiente",  "Cancelado",   RolRequerido.AGENTE,        True,  "Cancelar",      "Cancelar un ticket pendiente (justificar)"),
        ("En curso",   "Bloqueado",   RolRequerido.AGENTE,        True,  "Bloquear",      "Marcar como bloqueado (justificar)"),
        ("En curso",   "En revisión", RolRequerido.AGENTE,        False, "Enviar a revisión", "Pasar a En revisión"),
        ("En curso",   "Pendiente",   RolRequerido.AGENTE,        True,  "Devolver",      "Devolver a Pendiente (justificar)"),
        ("Bloqueado",  "En curso",    RolRequerido.AGENTE,        False, "Desbloquear",   "Reanudar trabajo desde Bloqueado"),
        ("Bloqueado",  "Cancelado",   RolRequerido.AGENTE_SENIOR, True,  "Cancelar (bloq.)", "Cancelar un ticket bloqueado"),
        ("En revisión","En curso",    RolRequerido.AGENTE,        True,  "Devolver a curso", "Devolver a En curso (justificar)"),
        ("En revisión","Cerrado",     RolRequerido.AGENTE_SENIOR, True,  "Cerrar",        "Cerrar ticket (verificado, justificar)"),
        ("En revisión","Cancelado",   RolRequerido.AGENTE_SENIOR, True,  "Cancelar (rev.)", "Cancelar en revisión"),
    ]
    for origen_n, destino_n, rol, req_com, nombre, descripcion in reglas:
        o = estados.get(origen_n)
        d = estados.get(destino_n)
        if not o or not d:
            logger.warning("Saltando regla %s→%s: estado no existe", origen_n, destino_n)
            continue
        db.add(Transicion(
            origen_id=o.id, destino_id=d.id, nombre=nombre, descripcion=descripcion,
            rol_requerido=rol, requiere_comentario=req_com,
            dispara_recalculo_sla=True, activo=True,
        ))
    db.commit()
    logger.info("Sembradas %d reglas de transición.", len(reglas))


def _seed_sla(db) -> None:
    """Políticas SLA por defecto según prioridad."""
    if db.query(SLAPolitica).count() > 0:
        logger.info("Políticas SLA ya sembradas. Omitiendo.")
        return
    politicas = [
        # (nombre, prioridad, minutos)
        ("SLA Crítica",  PrioridadTicket.CRITICA, 60 * 4),    # 4 horas
        ("SLA Alta",     PrioridadTicket.ALTA,    60 * 24),   # 1 día
        ("SLA Media",    PrioridadTicket.MEDIA,   60 * 72),   # 3 días
        ("SLA Baja",     PrioridadTicket.BAJA,    60 * 168),  # 7 días
    ]
    for nombre, prio, minutos in politicas:
        db.add(SLAPolitica(
            nombre=nombre, prioridad=prio, minutos_resolucion=minutos,
            es_default=True, activo=True,
        ))
    db.commit()
    logger.info("Sembradas %d políticas SLA.", len(politicas))


def _seed_catalogos(db) -> None:
    """Sembrado mínimo de catálogos: tipos de ticket y categorías."""
    if db.query(CatalogoItem).count() > 0:
        logger.info("Catálogos ya sembrados. Omitiendo.")
        return
    items = [
        # (tipo, codigo, nombre, color, orden)
        (TipoCatalogo.TIPO_TICKET, "INC",   "Incidencia",  "#dc2626", 1),
        (TipoCatalogo.TIPO_TICKET, "REQ",   "Requerimiento","#2563eb", 2),
        (TipoCatalogo.TIPO_TICKET, "BUG",   "Bug",         "#ea580c", 3),
        (TipoCatalogo.TIPO_TICKET, "CONS",  "Consulta",    "#64748b", 4),
        (TipoCatalogo.CATEGORIA,   "HW",    "Hardware",    "#7c3aed", 1),
        (TipoCatalogo.CATEGORIA,   "SW",    "Software",    "#0ea5e9", 2),
        (TipoCatalogo.CATEGORIA,   "RED",   "Redes",       "#16a34a", 3),
        (TipoCatalogo.CATEGORIA,   "SEG",   "Seguridad",   "#dc2626", 4),
        (TipoCatalogo.MODULO,      "AUTH",  "Autenticación","#9333ea", 1),
        (TipoCatalogo.MODULO,      "API",   "API",         "#2563eb", 2),
        (TipoCatalogo.MODULO,      "UI",    "Interfaz",    "#0ea5e9", 3),
    ]
    for tipo, codigo, nombre, color, orden in items:
        db.add(CatalogoItem(
            tipo=tipo, codigo=codigo, nombre=nombre, descripcion="",
            color=color, orden=orden, activo=True,
        ))
    db.commit()
    logger.info("Sembrados %d ítems de catálogo.", len(items))


def _seed_tickets_ejemplo(db) -> None:
    """Crea 6 tickets de ejemplo (1 por cada estado) para que el Kanban no esté vacío."""
    if db.query(__import__("app").models.ticket.Ticket).count() > 0:
        return
    from app.models.ticket import Ticket
    estados = {e.nombre: e for e in db.query(Estado).all()}
    admin = db.execute(select(Usuario).where(Usuario.username == settings.bootstrap_admin_username)).scalar_one_or_none()
    if not admin:
        return

    ejemplos = [
        # (titulo, prioridad, estado_nombre, descripcion)
        ("Login falla con error 500 tras cambio de password",  PrioridadTicket.CRITICA, "Pendiente",
         "Reportado por 3 usuarios. Logs muestran bcrypt.InvaliSaltError."),
        ("Actualizar README con nueva API v2",                PrioridadTicket.BAJA,    "En curso",
         "Documentar los 3 nuevos endpoints."),
        ("Esperando entrega de proveedor para licencias",     PrioridadTicket.MEDIA,   "Bloqueado",
         "Proveedor confirma entrega 2026-11-15."),
        ("Revisar PR #234 - refactor módulo auth",            PrioridadTicket.MEDIA,   "En revisión",
         "QA pasó; falta sign-off del tech lead."),
        ("Reporte de cierre: deploy producción exitoso",      PrioridadTicket.ALTA,    "Cerrado",
         "Ticket 100% completado, sin pendientes."),
        ("Duplicado de ticket TKT-00003, se cancela",         PrioridadTicket.BAJA,    "Cancelado",
         "Cancelado por duplicidad."),
    ]
    for idx, (titulo, prio, estado_nombre, desc) in enumerate(ejemplos):
        est = estados.get(estado_nombre)
        if not est:
            continue
        db.add(Ticket(
            codigo=f"TKT-{idx + 1:05d}",
            titulo=titulo, descripcion=desc,
            estado_id=est.id, prioridad=prio,
            creador_id=admin.id, asignado_id=admin.id,
            posicion=0,
        ))
    db.commit()
    logger.info("Sembrados %d tickets de ejemplo.", len(ejemplos))


def init_all() -> None:
    """Ejecuta todos los pasos de inicialización."""
    _crear_tablas()
    db = SessionLocal()
    try:
        _seed_admin(db)
        _seed_estados(db)
        _seed_transiciones(db)
        _seed_sla(db)
        _seed_catalogos(db)
        _seed_tickets_ejemplo(db)
        logger.info("Inicialización completa.")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    init_all()
