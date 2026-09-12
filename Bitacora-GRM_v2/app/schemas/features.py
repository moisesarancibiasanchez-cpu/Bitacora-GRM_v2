"""
Schemas Pydantic para las nuevas funcionalidades estilo Trello:
- Etiquetas
- Checklists
- Comentarios
- Adjuntos
- Búsqueda y filtros
- Automatizaciones
"""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, ConfigDict


# ==========================================
# ETIQUETAS
# ==========================================
class EtiquetaBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=60)
    color: str = Field(default="#6b7280", pattern=r"^#[0-9A-Fa-f]{6}$")
    categoria: str = Field(default="general", max_length=40)
    descripcion: Optional[str] = None


class EtiquetaCreate(EtiquetaBase):
    pass


class EtiquetaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=60)
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    categoria: Optional[str] = Field(None, max_length=40)
    descripcion: Optional[str] = None
    activo: Optional[bool] = None


class EtiquetaRead(EtiquetaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


# ==========================================
# CHECKLISTS
# ==========================================
class ChecklistItemBase(BaseModel):
    texto: str = Field(..., min_length=1, max_length=500)
    orden: int = 0
    asignado_id: Optional[int] = None
    fecha_vencimiento: Optional[str] = None


class ChecklistItemCreate(ChecklistItemBase):
    pass


class ChecklistItemUpdate(BaseModel):
    texto: Optional[str] = Field(None, min_length=1, max_length=500)
    completado: Optional[bool] = None
    orden: Optional[int] = None
    asignado_id: Optional[int] = None
    fecha_vencimiento: Optional[str] = None


class ChecklistItemRead(ChecklistItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    completado: bool


class ChecklistBase(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=200)
    orden: int = 0


class ChecklistCreate(ChecklistBase):
    items: List[ChecklistItemCreate] = Field(default_factory=list)


class ChecklistUpdate(BaseModel):
    titulo: Optional[str] = Field(None, min_length=1, max_length=200)
    orden: Optional[int] = None
    posicion: Optional[int] = None


class ChecklistRead(ChecklistBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    items: List[ChecklistItemRead] = Field(default_factory=list)
    progreso: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime] = None


# ==========================================
# COMENTARIOS
# ==========================================
class ComentarioBase(BaseModel):
    texto: str = Field(..., min_length=1, max_length=5000)
    es_interno: bool = False


class ComentarioCreate(ComentarioBase):
    pass


class ComentarioUpdate(BaseModel):
    texto: str = Field(..., min_length=1, max_length=5000)


class MencionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usuario_id: int
    notificado: int


class ComentarioRead(ComentarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    usuario_id: int
    editado: bool
    texto_original: Optional[str] = None
    menciones: List[MencionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None


class ComentarioReadWithAuthor(ComentarioRead):
    """Comentario con datos del autor para mostrar en UI."""
    autor_nombre: Optional[str] = None
    autor_username: Optional[str] = None
    autor_rol: Optional[str] = None


# ==========================================
# ADJUNTOS
# ==========================================
class AdjuntoBase(BaseModel):
    descripcion: Optional[str] = None


class AdjuntoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    usuario_id: int
    nombre_original: str
    nombre_storage: str
    ruta: str
    mime_type: Optional[str] = None
    tamano_bytes: int
    descripcion: Optional[str] = None
    tamano_legible: Optional[str] = None
    es_imagen: Optional[bool] = None
    created_at: datetime


# ==========================================
# BÚSQUEDA Y FILTROS
# ==========================================
class FiltroTicket(BaseModel):
    """Filtros avanzados para búsqueda de tickets."""
    texto: Optional[str] = Field(None, description="Búsqueda libre en título/descripción/código")
    estados: Optional[List[int]] = Field(None, description="IDs de estados")
    prioridades: Optional[List[str]] = Field(None, description="baja, media, alta, critica")
    tipos: Optional[List[str]] = Field(None, description="incidencia, solicitud, cambio, problema")
    etiquetas: Optional[List[int]] = Field(None, description="IDs de etiquetas (OR)")
    etiquetas_all: Optional[List[int]] = Field(None, description="IDs de etiquetas (AND)")
    asignados: Optional[List[int]] = Field(None, description="IDs de usuarios asignados")
    creadores: Optional[List[int]] = Field(None, description="IDs de usuarios creadores")
    catalogos: Optional[List[int]] = Field(None, description="IDs de tipos de catálogo")
    fecha_desde: Optional[datetime] = None
    fecha_hasta: Optional[datetime] = None
    sla_cumplido: Optional[int] = Field(None, description="1=cumplido, 0=vencido, -1=pendiente")
    con_vencimiento_proximo: Optional[int] = Field(None, description="Horas")
    solo_sin_asignar: Optional[bool] = None
    solo_con_comentarios: Optional[bool] = None
    solo_con_adjuntos: Optional[bool] = None
    ordenar_por: Optional[str] = Field(
        default="created_at", description="created_at, updated_at, prioridad, fecha_vencimiento_sla"
    )
    orden: Optional[str] = Field(default="desc", description="asc, desc")
    limite: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# ==========================================
# AUTOMATIZACIONES (BUTLER)
# ==========================================
class CondicionRegla(BaseModel):
    campo: str
    operador: str = Field(..., description="==, !=, in, not_in, contains, gt, lt")
    valor: Any


class AccionRegla(BaseModel):
    tipo: str = Field(..., description="asignar_a, cambiar_estado, agregar_etiqueta, etc.")
    parametros: dict = Field(default_factory=dict)


class ReglaAutomatizacionBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    descripcion: Optional[str] = None
    disparador: str = Field(..., min_length=1, max_length=60)
    condiciones: List[CondicionRegla] = Field(default_factory=list)
    acciones: List[AccionRegla] = Field(..., min_length=1)
    prioridad: int = 100
    activo: bool = True


class ReglaAutomatizacionCreate(ReglaAutomatizacionBase):
    pass


class ReglaAutomatizacionUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    disparador: Optional[str] = None
    condiciones: Optional[List[CondicionRegla]] = None
    acciones: Optional[List[AccionRegla]] = None
    prioridad: Optional[int] = None
    activo: Optional[bool] = None


class ReglaAutomatizacionRead(ReglaAutomatizacionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    creador_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class EjecucionAutomatizacionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    regla_id: int
    ticket_id: Optional[int] = None
    contexto: Optional[dict] = None
    exito: int
    detalle: Optional[str] = None
    created_at: datetime


# ==========================================
# TICKET DETALLE (vista de tarjeta expandida)
# ==========================================
class TicketDetalleRead(BaseModel):
    """Ticket con todas las relaciones cargadas para vista de detalle."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    codigo: str
    titulo: str
    descripcion: str
    tipo: str
    prioridad: str
    estado_id: int
    estado_nombre: Optional[str] = None
    creador_id: int
    creador_nombre: Optional[str] = None
    asignado_id: Optional[int] = None
    asignado_nombre: Optional[str] = None
    catalogo_tipo_id: Optional[int] = None
    catalogo_tipo_nombre: Optional[str] = None
    datos_catalogo: Optional[str] = None
    fecha_vencimiento_sla: Optional[datetime] = None
    sla_cumplido: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    etiquetas: List[EtiquetaRead] = Field(default_factory=list)
    checklists: List[ChecklistRead] = Field(default_factory=list)
    comentarios: List[ComentarioReadWithAuthor] = Field(default_factory=list)
    adjuntos: List[AdjuntoRead] = Field(default_factory=list)
    total_comentarios: int = 0
    total_adjuntos: int = 0
    total_checklists: int = 0
    progreso_checklists: dict = Field(default_factory=dict)
