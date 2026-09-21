"""
Schemas Pydantic para validación de entrada/salida de la API.
"""
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
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

# LOV de Ambiente (entorno de la incidencia). Reemplaza al campo "Categoría".
AMBIENTE_PERMITIDOS = {
    "QA",
    "PRODUCCION",
    "",  # vacío permitido (no asignado)
}

# LOV de Ítem (subsistema o canal afectado).
ITEM_PERMITIDOS = {
    "Portal WEB APEX",
    "Email",
    "Base de Datos",
    "",  # vacío permitido (no asignado)
}

# LOV de resultado de pruebas (sincronizado con app.models.ticket.RESULTADO_PRUEBAS_LOV).
# Actualizado: "POSTERGADA A GARANTÍA" → "POSTERGADA"; se agrega "DESESTIMADA".
RESULTADO_PRUEBAS_PERMITIDOS = {
    "OK",
    "N/A",
    "OK CON OBS.",
    "POSTERGADA",
    "DESESTIMADA",
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
    # NOTA sobre ``datos_catalogo``:
    # El modelo SQLAlchemy declara esta columna como ``Column(JSON, ...)``,
    # y dependiendo del driver/versión de PostgreSQL el valor puede llegar
    # como ``dict`` nativo (psycopg + JSONB) o como ``str`` con el JSON
    # serializado (psycopg2 + JSON nativo en columnas migradas). Para que
    # la API NO devuelva HTTP 500 al listar tickets legacy, aceptamos
    # ambos tipos y normalizamos a ``dict`` en el validador ``mode="before"``.
    datos_catalogo: Optional[Union[Dict[str, Any], str]] = None

    @field_validator("datos_catalogo", mode="before")
    @classmethod
    def _coerce_datos_catalogo(cls, v):
        """Acepta dict nativo o string JSON; normaliza a dict (o None)."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return {}
            try:
                parsed = json.loads(s)
                # Si el JSON parseado es un dict, devolverlo; si es lista/otro,
                # envolverlo para mantener la coherencia con el tipo declarado.
                if isinstance(parsed, dict):
                    return parsed
                return {"_value": parsed}
            except (ValueError, TypeError):
                # JSON malformado: no rompemos el endpoint, devolvemos dict
                # vacío para que el resto del ticket se serialice bien.
                return {}
        # Cualquier otro tipo (lista, int, etc.): mantener valor seguro
        if isinstance(v, (list, tuple)):
            return {"_value": list(v)}
        return {}

    # === Campos extendidos del módulo de Incidencias ===
    modulo: Optional[str] = Field(
        default=None, max_length=80,
        description="Módulo del sistema (LOV: Control ERM, Gobierno, ...)",
    )
    # Ambiente: reemplaza al antiguo campo "Categoría".
    ambiente: Optional[str] = Field(
        default=None, max_length=40,
        description="Ambiente de la incidencia (LOV: QA, PRODUCCION)",
    )
    # Ítem: subsistema o canal afectado.
    item: Optional[str] = Field(
        default=None, max_length=80,
        description="Ítem o subsistema afectado (LOV: Portal WEB APEX, Email, Base de Datos)",
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
        description="Resultado de pruebas (LOV: OK, N/A, OK CON OBS., POSTERGADA, DESESTIMADA, NOK)",
    )

    # NOTA: Los validadores LOV de modulo/ambiente/item/resultado_pruebas
    # vivían aquí antes, pero se ejecutaban también durante la SERIALIZACIÓN
    # de TicketRead (que hereda de TicketBase), lo que provocaba HTTP 500
    # en GET /api/v1/tickets y /api/v1/tickets/{id} cuando había tickets
    # con valores legacy fuera de las LOV permitidas.
    #
    # Los validadores se trasladaron a TicketCreate / TicketUpdate (donde
    # sí tiene sentido validar la ENTRADA del usuario). TicketRead ahora
    # acepta cualquier valor para estos campos y los devuelve tal cual.


class TicketCreate(TicketBase):
    estado_id: Optional[int] = None  # Si None, se asigna el estado inicial

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

    @field_validator("ambiente")
    @classmethod
    def _check_ambiente(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in AMBIENTE_PERMITIDOS:
            raise ValueError(
                f"ambiente debe ser uno de: {sorted(a for a in AMBIENTE_PERMITIDOS if a)}"
            )
        return v_norm or None

    @field_validator("item")
    @classmethod
    def _check_item(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in ITEM_PERMITIDOS:
            raise ValueError(
                f"item debe ser uno de: {sorted(i for i in ITEM_PERMITIDOS if i)}"
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


class TicketUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    prioridad: Optional[str] = None
    asignado_id: Optional[int] = None
    datos_catalogo: Optional[Dict[str, Any]] = None
    # === Campos de scheduling (Gantt) ===
    # Aceptan ISO 'YYYY-MM-DD' o ISO con hora. Si se envían ambos, fecha_inicio
    # debe ser <= fecha_vencimiento_sla; la validación de coherencia se hace
    # en el servicio (``TicketService.actualizar_campos``).
    fecha_inicio: Optional[datetime] = None
    fecha_vencimiento_sla: Optional[datetime] = None
    # === Campos extendidos del módulo de Incidencias ===
    modulo: Optional[str] = Field(default=None, max_length=80)
    ambiente: Optional[str] = Field(default=None, max_length=40)
    item: Optional[str] = Field(default=None, max_length=80)
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

    @field_validator("ambiente")
    @classmethod
    def _check_ambiente(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in AMBIENTE_PERMITIDOS:
            raise ValueError(
                f"ambiente debe ser uno de: {sorted(a for a in AMBIENTE_PERMITIDOS if a)}"
            )
        return v_norm or None

    @field_validator("item")
    @classmethod
    def _check_item(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_norm = v.strip()
        if v_norm and v_norm not in ITEM_PERMITIDOS:
            raise ValueError(
                f"item debe ser uno de: {sorted(i for i in ITEM_PERMITIDOS if i)}"
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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
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
