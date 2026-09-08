"""Paquete de modelos: importa todos los modelos para que Alembic los detecte."""
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado, TransicionEstado
from app.models.ticket import Ticket, HistorialEstado, Prioridad, TipoIncidencia
from app.models.auditoria import Auditoria
from app.models.catalogo import CatalogoTipo, CatalogoItem
from app.models.etiqueta import Etiqueta, ticket_etiquetas
from app.models.checklist import Checklist, ChecklistItem
from app.models.comentario import Comentario, MencionUsuario
from app.models.adjunto import Adjunto
from app.models.automacion import ReglaAutomatizacion, EjecucionAutomatizacion

__all__ = [
    "Usuario", "RolUsuario",
    "Estado", "TransicionEstado",
    "Ticket", "HistorialEstado", "Prioridad", "TipoIncidencia",
    "Auditoria",
    "CatalogoTipo", "CatalogoItem",
    "Etiqueta", "ticket_etiquetas",
    "Checklist", "ChecklistItem",
    "Comentario", "MencionUsuario",
    "Adjunto",
    "ReglaAutomatizacion", "EjecucionAutomatizacion",
]
