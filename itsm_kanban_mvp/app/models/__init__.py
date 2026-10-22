"""Modelos del dominio ITSM/Kanban.

Importar todos los modelos aquí garantiza que `Base.metadata.create_all()`
de SQLAlchemy los registre para la creación de tablas.
"""
from .usuario import Usuario, RolUsuario  # noqa: F401
from .estado import Estado, CategoriaEstado  # noqa: F401
from .transicion import Transicion, RolRequerido  # noqa: F401
from .ticket import Ticket, PrioridadTicket  # noqa: F401
from .auditoria import AuditoriaEvento, TipoEvento  # noqa: F401
from .sla import SLAPolitica  # noqa: F401
from .catalogo import CatalogoItem, TipoCatalogo  # noqa: F401

__all__ = [
    "Usuario",
    "RolUsuario",
    "Estado",
    "CategoriaEstado",
    "Transicion",
    "RolRequerido",
    "Ticket",
    "PrioridadTicket",
    "AuditoriaEvento",
    "TipoEvento",
    "SLAPolitica",
    "CatalogoItem",
    "TipoCatalogo",
]
