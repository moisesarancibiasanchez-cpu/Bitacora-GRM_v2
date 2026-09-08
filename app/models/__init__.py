"""Paquete de modelos: importa todos los modelos para que Alembic los detecte."""
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado, TransicionEstado
from app.models.ticket import Ticket, HistorialEstado, Prioridad, TipoIncidencia
from app.models.auditoria import Auditoria
from app.models.catalogo import CatalogoTipo, CatalogoItem

__all__ = [
    "Usuario", "RolUsuario",
    "Estado", "TransicionEstado",
    "Ticket", "HistorialEstado", "Prioridad", "TipoIncidencia",
    "Auditoria",
    "CatalogoTipo", "CatalogoItem",
]
