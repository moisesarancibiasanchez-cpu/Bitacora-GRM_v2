"""Paquete de modelos: importa todos los modelos para que Alembic los detecte."""
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado, TransicionEstado
from app.models.ticket import Ticket, HistorialEstado, Prioridad, TipoIncidencia, ticket_miembros
from app.models.auditoria import Auditoria
from app.models.catalogo import CatalogoTipo, CatalogoItem
from app.models.etiqueta import Etiqueta, ticket_etiquetas
from app.models.checklist import Checklist, ChecklistItem
from app.models.comentario import Comentario, MencionUsuario
from app.models.adjunto import Adjunto
from app.models.automacion import ReglaAutomatizacion, EjecucionAutomatizacion
# === Nuevos modelos estilo Trello ===
from app.models.espacio import Espacio, Tablero, PermisoTablero, espacio_miembros
from app.models.watch import Watch, Reaccion, Notificacion
from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
from app.models.butler_extras import (
    BotonTarjeta, EjecucionBoton, ComandoProgramado, EjecucionComando,
)

__all__ = [
    "Usuario", "RolUsuario",
    "Estado", "TransicionEstado",
    "Ticket", "HistorialEstado", "Prioridad", "TipoIncidencia", "ticket_miembros",
    "Auditoria",
    "CatalogoTipo", "CatalogoItem",
    "Etiqueta", "ticket_etiquetas",
    "Checklist", "ChecklistItem",
    "Comentario", "MencionUsuario",
    "Adjunto",
    "ReglaAutomatizacion", "EjecucionAutomatizacion",
    # Nuevos
    "Espacio", "Tablero", "PermisoTablero", "espacio_miembros",
    "Watch", "Reaccion", "Notificacion",
    "CampoPersonalizado", "ValorCampo",
    "BotonTarjeta", "EjecucionBoton", "ComandoProgramado", "EjecucionComando",
]
