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
from app.schemas.trello import (
    EspacioCreate, EspacioUpdate, EspacioRead, EspacioDetalle,
    TableroCreate, TableroUpdate, TableroRead,
    PermisoTableroCreate, PermisoTableroRead,
    WatchCreate, WatchRead,
    ReaccionCreate, ReaccionRead, ReaccionGrupo,
    CampoPersonalizadoCreate, CampoPersonalizadoUpdate, CampoPersonalizadoRead,
    ValorCampoCreate, ValorCampoRead,
    BotonTarjetaCreate, BotonTarjetaUpdate, BotonTarjetaRead,
    ComandoProgramadoCreate, ComandoProgramadoUpdate, ComandoProgramadoRead,
    NotificacionRead, TicketMetadataUpdate, VistaTablaFila,
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
    # Nuevos Trello
    "EspacioCreate", "EspacioUpdate", "EspacioRead", "EspacioDetalle",
    "TableroCreate", "TableroUpdate", "TableroRead",
    "PermisoTableroCreate", "PermisoTableroRead",
    "WatchCreate", "WatchRead",
    "ReaccionCreate", "ReaccionRead", "ReaccionGrupo",
    "CampoPersonalizadoCreate", "CampoPersonalizadoUpdate", "CampoPersonalizadoRead",
    "ValorCampoCreate", "ValorCampoRead",
    "BotonTarjetaCreate", "BotonTarjetaUpdate", "BotonTarjetaRead",
    "ComandoProgramadoCreate", "ComandoProgramadoUpdate", "ComandoProgramadoRead",
    "NotificacionRead", "TicketMetadataUpdate", "VistaTablaFila",
]
