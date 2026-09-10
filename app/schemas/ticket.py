"""
Schemas Pydantic para validación de entrada/salida de la API.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


# ============== Estado ==============
class EstadoBase(BaseModel):
    nombre: str = Field(..., max_length=80)
    descripcion: Optional[str] = None
    color: str = Field(default="#94a3b8", max_length=20)
    orden: int = 0
    es_inicial: bool = False
    es_final: bool = False
    categoria: str = "abierto"
    sla_horas: Optional[int] = None


class EstadoRead(EstadoBase):
    id: int
    responsable_id: Optional[int] = Field(
        default=None,
        description="ID del usuario responsable de la columna (None = sin asignar)",
    )
    model_config = ConfigDict(from_attributes=True)


# ============== Transición ==============
class TransicionEstadoRead(BaseModel):
    id: int
    estado_origen_id: int
    estado_destino_id: int
    rol_requerido: str
    requiere_comentario: bool
    descripcion: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ============== Usuario ==============
class UsuarioRead(BaseModel):
    id: int
    username: str
    nombre_completo: str
    email: str
    rol: str
    departamento: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ============== Ticket ==============
class TicketBase(BaseModel):
    titulo: str = Field(..., max_length=200)
    descripcion: str
    tipo: str = "incidencia"
    prioridad: str = "media"
    asignado_id: Optional[int] = None
    catalogo_tipo_id: Optional[int] = None
    datos_catalogo: Optional[Dict[str, Any]] = None


class TicketCreate(TicketBase):
    estado_id: Optional[int] = None  # Si None, se asigna el estado inicial


class TicketUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    prioridad: Optional[str] = None
    asignado_id: Optional[int] = None
    datos_catalogo: Optional[Dict[str, Any]] = None


class TicketRead(TicketBase):
    id: int
    codigo: str
    estado_id: int
    creador_id: int
    fecha_vencimiento_sla: Optional[datetime] = None
    sla_cumplido: int
    created_at: datetime
    updated_at: datetime
    estado: Optional[EstadoRead] = None
    creador: Optional[UsuarioRead] = None
    asignado: Optional[UsuarioRead] = None
    model_config = ConfigDict(from_attributes=True)


# ============== Cambio de estado (drag & drop) ==============
class CambioEstadoRequest(BaseModel):
    """Petición para cambiar el estado de un ticket (drag & drop Kanban)."""
    estado_id: int = Field(..., description="ID del estado destino")
    comentario: Optional[str] = Field(
        None, description="Motivo del cambio (obligatorio en algunas transiciones)"
    )
    orden: Optional[int] = Field(
        None, description="Posición en la columna destino"
    )


class CambioEstadoResponse(BaseModel):
    success: bool
    message: str
    ticket: Optional[TicketRead] = None
    task_id: Optional[str] = Field(None, description="ID de la tarea Celery lanzada")


# ============== Auditoría ==============
class AuditoriaRead(BaseModel):
    id: int
    ticket_id: int
    usuario_id: int
    accion: str
    valor_anterior: Optional[Dict[str, Any]] = None
    valor_nuevo: Optional[Dict[str, Any]] = None
    comentario: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ============== Error ==============
class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
