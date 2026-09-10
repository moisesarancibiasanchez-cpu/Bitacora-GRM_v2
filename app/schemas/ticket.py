"""
Schemas Pydantic para validación de entrada/salida de la API.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict, field_validator


# LOV de módulos del sistema (sincronizado con app.models.ticket.MODULOS_LOV)
MODULOS_PERMITIDOS = {
    "Control ERM",
    "Gobierno",
    "Incidencias",
    "Validación",
    "Auditoria",
    "Filiales",
    "Información Inventario",
    "Registro de Información",
    "Documentación",
    "Mejoras Transversales",
    "Seguimiento y Control",
    "",  # vacío permitido (no asignado)
}

# LOV de resultado de pruebas
RESULTADO_PRUEBAS_PERMITIDOS = {
    "OK",
    "N/A",
    "OK CON OBS.",
    "POSTERGADA A GARANTÍA",
    "NOK",
    "",  # vacío permitido
}


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


class EstadoCreate(EstadoBase):
    """Payload para crear un nuevo estado (POST /estados)."""
    responsable_id: Optional[int] = Field(
        default=None,
        description="ID del usuario responsable de la columna (None = sin asignar)",
    )

    @field_validator("nombre")
    @classmethod
    def _check_nombre(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("nombre no puede estar vacío")
        return v


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
    # === Campos extendidos del módulo de Incidencias ===
    modulo: Optional[str] = Field(
        default=None, max_length=80,
        description="Módulo del sistema (LOV: Control ERM, Gobierno, ...)",
    )
    vista: Optional[str] = Field(
        default=None, max_length=200,
        description="Vista o pantalla específica",
    )
    hu_o_caso_prueba: Optional[str] = Field(
        default=None, max_length=200,
        description="Historia de usuario o caso de prueba asociado",
    )
    nota_observacion: Optional[str] = Field(
        default=None,
        description="Nota u observación libre",
    )
    resultado_pruebas: Optional[str] = Field(
        default=None, max_length=40,
        description="Resultado de pruebas (LOV: OK, N/A, OK CON OBS., POSTERGADA A GARANTÍA, NOK)",
    )

    @field_validator("modulo")
    @classmethod
    def _check_modulo(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in MODULOS_PERMITIDOS:
            raise ValueError(
                f"modulo debe ser uno de: {sorted(m for m in MODULOS_PERMITIDOS if m)}"
            )
        return v_norm or None

    @field_validator("resultado_pruebas")
    @classmethod
    def _check_resultado(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in RESULTADO_PRUEBAS_PERMITIDOS:
            raise ValueError(
                f"resultado_pruebas debe ser uno de: {sorted(r for r in RESULTADO_PRUEBAS_PERMITIDOS if r)}"
            )
        return v_norm or None


class TicketCreate(TicketBase):
    estado_id: Optional[int] = None  # Si None, se asigna el estado inicial


class TicketUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    prioridad: Optional[str] = None
    asignado_id: Optional[int] = None
    datos_catalogo: Optional[Dict[str, Any]] = None
    # === Campos extendidos del módulo de Incidencias ===
    modulo: Optional[str] = Field(default=None, max_length=80)
    vista: Optional[str] = Field(default=None, max_length=200)
    hu_o_caso_prueba: Optional[str] = Field(default=None, max_length=200)
    nota_observacion: Optional[str] = None
    resultado_pruebas: Optional[str] = Field(default=None, max_length=40)

    @field_validator("modulo")
    @classmethod
    def _check_modulo(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in MODULOS_PERMITIDOS:
            raise ValueError(
                f"modulo debe ser uno de: {sorted(m for m in MODULOS_PERMITIDOS if m)}"
            )
        return v_norm or None

    @field_validator("resultado_pruebas")
    @classmethod
    def _check_resultado(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in RESULTADO_PRUEBAS_PERMITIDOS:
            raise ValueError(
                f"resultado_pruebas debe ser uno de: {sorted(r for r in RESULTADO_PRUEBAS_PERMITIDOS if r)}"
            )
        return v_norm or None


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
