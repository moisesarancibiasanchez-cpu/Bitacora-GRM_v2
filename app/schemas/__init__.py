"""Paquete de schemas Pydantic."""
from app.schemas.ticket import (
    EstadoBase, EstadoRead, TransicionEstadoRead, UsuarioRead,
    TicketBase, TicketCreate, TicketUpdate, TicketRead,
    CambioEstadoRequest, CambioEstadoResponse, AuditoriaRead, ErrorResponse,
)
from app.schemas.features import (
    EtiquetaBase, EtiquetaCreate, EtiquetaUpdate, EtiquetaRead,
    ChecklistBase, ChecklistCreate, ChecklistUpdate, ChecklistRead,
    ChecklistItemBase, ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemRead,
    ComentarioBase, ComentarioCreate, ComentarioUpdate, ComentarioRead, ComentarioReadWithAuthor,
    MencionRead, AdjuntoBase, AdjuntoRead,
    FiltroTicket,
    ReglaAutomatizacionBase, ReglaAutomatizacionCreate, ReglaAutomatizacionUpdate,
    ReglaAutomatizacionRead, EjecucionAutomatizacionRead,
    CondicionRegla, AccionRegla,
    TicketDetalleRead,
)

__all__ = [
    # Base
    "EstadoBase", "EstadoRead", "TransicionEstadoRead", "UsuarioRead",
    "TicketBase", "TicketCreate", "TicketUpdate", "TicketRead",
    "CambioEstadoRequest", "CambioEstadoResponse", "AuditoriaRead", "ErrorResponse",
    # Trello features
    "EtiquetaBase", "EtiquetaCreate", "EtiquetaUpdate", "EtiquetaRead",
    "ChecklistBase", "ChecklistCreate", "ChecklistUpdate", "ChecklistRead",
    "ChecklistItemBase", "ChecklistItemCreate", "ChecklistItemUpdate", "ChecklistItemRead",
    "ComentarioBase", "ComentarioCreate", "ComentarioUpdate", "ComentarioRead", "ComentarioReadWithAuthor",
    "MencionRead", "AdjuntoBase", "AdjuntoRead",
    "FiltroTicket",
    "ReglaAutomatizacionBase", "ReglaAutomatizacionCreate", "ReglaAutomatizacionUpdate",
    "ReglaAutomatizacionRead", "EjecucionAutomatizacionRead",
    "CondicionRegla", "AccionRegla",
    "TicketDetalleRead",
]
