"""
Schemas Pydantic para las nuevas funcionalidades estilo Trello:
Espacios, Tableros, Permisos, Watch, Reacciones, Custom Fields, Botones,
Comandos Programados, Notificaciones.
"""
from datetime import datetime
from typing import List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


# ==========================================
# ESPACIOS (WORKSPACES)
# ==========================================
class EspacioBase(BaseModel):
    nombre: str = Field(..., max_length=120)
    descripcion: Optional[str] = None
    plan: str = Field(default="gratis", max_length=30)
    es_publico: bool = False
    color: str = Field(default="#6366f1", max_length=20)
    icono: str = Field(default="espacio", max_length=40)


class EspacioCreate(EspacioBase):
    pass


class EspacioUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    plan: Optional[str] = None
    es_publico: Optional[bool] = None
    color: Optional[str] = None
    icono: Optional[str] = None


class EspacioRead(EspacioBase):
    id: int
    propietario_id: int
    total_miembros: int = 0
    total_tableros: int = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EspacioDetalle(EspacioRead):
    miembros: List[dict] = []
    tableros: List[dict] = []


# ==========================================
# TABLEROS
# ==========================================
class TableroBase(BaseModel):
    nombre: str = Field(..., max_length=120)
    descripcion: Optional[str] = None
    visibilidad: str = Field(default="privado")  # privado | espacio | publico
    color_fondo: str = Field(default="#0ea5e9", max_length=20)
    imagen_fondo: Optional[str] = None


class TableroCreate(TableroBase):
    espacio_id: int


class TableroUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    visibilidad: Optional[str] = None
    color_fondo: Optional[str] = None
    imagen_fondo: Optional[str] = None
    archivado: Optional[bool] = None


class TableroRead(TableroBase):
    id: int
    espacio_id: int
    propietario_id: int
    archivado: bool
    slug_publico: Optional[str] = None
    total_tickets: int = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# PERMISOS DE TABLERO
# ==========================================
class PermisoTableroCreate(BaseModel):
    usuario_id: int
    rol_tablero: str = "editor"  # admin | editor | lector
    notificar: bool = True


class PermisoTableroRead(BaseModel):
    id: int
    tablero_id: int
    usuario_id: int
    rol_tablero: str
    notificar: bool
    invitado_por_id: Optional[int] = None
    usuario: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# WATCH (SUSCRIPCIONES)
# ==========================================
class WatchCreate(BaseModel):
    tipo_objeto: str  # ticket | tablero | espacio | lista
    objeto_id: int
    canal: str = "all"  # web | email | push | all


class WatchRead(BaseModel):
    id: int
    usuario_id: int
    tipo_objeto: str
    objeto_id: int
    activo: bool
    canal: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# REACCIONES
# ==========================================
class ReaccionCreate(BaseModel):
    tipo_objeto: str  # comentario | ticket
    objeto_id: int
    emoji: str = Field(..., max_length=16)


class ReaccionRead(BaseModel):
    id: int
    usuario_id: int
    tipo_objeto: str
    objeto_id: int
    emoji: str
    usuario: Optional[dict] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReaccionGrupo(BaseModel):
    """Agrupa reacciones por emoji (para UI)."""
    emoji: str
    total: int
    usuarios: List[int] = []
    yo_reaccione: bool = False


# ==========================================
# CAMPOS PERSONALIZADOS
# ==========================================
class CampoPersonalizadoBase(BaseModel):
    nombre: str = Field(..., max_length=80)
    tipo: str  # texto | numero | dropdown | checkbox | fecha | url
    configuracion: Optional[dict] = None
    requerido: bool = False
    posicion: int = 0
    color: str = "#6366f1"


class CampoPersonalizadoCreate(CampoPersonalizadoBase):
    tablero_id: int


class CampoPersonalizadoUpdate(BaseModel):
    nombre: Optional[str] = None
    configuracion: Optional[dict] = None
    requerido: Optional[bool] = None
    posicion: Optional[int] = None
    activo: Optional[bool] = None
    color: Optional[str] = None


class CampoPersonalizadoRead(CampoPersonalizadoBase):
    id: int
    tablero_id: int
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ValorCampoCreate(BaseModel):
    campo_id: int
    valor_texto: Optional[str] = None
    valor_numero: Optional[float] = None
    valor_booleano: Optional[bool] = None
    valor_fecha: Optional[datetime] = None


class ValorCampoRead(BaseModel):
    id: int
    campo_id: int
    ticket_id: int
    valor_texto: Optional[str] = None
    valor_numero: Optional[float] = None
    valor_booleano: Optional[bool] = None
    valor_fecha: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# BOTONES DE TARJETA / TABLERO
# ==========================================
class BotonTarjetaBase(BaseModel):
    nombre: str = Field(..., max_length=80)
    descripcion: Optional[str] = None
    ambito: str = "tarjeta"  # tarjeta | tablero
    color: str = "#6366f1"
    icono: str = "⚡"
    acciones: List[dict] = []
    requiere_confirmacion: bool = False
    posicion: int = 0


class BotonTarjetaCreate(BotonTarjetaBase):
    tablero_id: Optional[int] = None


class BotonTarjetaUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    color: Optional[str] = None
    icono: Optional[str] = None
    acciones: Optional[List[dict]] = None
    requiere_confirmacion: Optional[bool] = None
    posicion: Optional[int] = None
    activo: Optional[bool] = None


class BotonTarjetaRead(BotonTarjetaBase):
    id: int
    tablero_id: Optional[int] = None
    activo: bool
    creador_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# COMANDOS PROGRAMADOS (BUTLER CRON)
# ==========================================
class ComandoProgramadoBase(BaseModel):
    nombre: str = Field(..., max_length=120)
    descripcion: Optional[str] = None
    cron_expression: str
    timezone: str = "UTC"
    acciones: List[dict] = []


class ComandoProgramadoCreate(ComandoProgramadoBase):
    tablero_id: Optional[int] = None


class ComandoProgramadoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    acciones: Optional[List[dict]] = None
    activo: Optional[bool] = None


class ComandoProgramadoRead(ComandoProgramadoBase):
    id: int
    tablero_id: Optional[int] = None
    activo: bool
    ultima_ejecucion: Optional[str] = None
    proxima_ejecucion: Optional[str] = None
    creador_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# NOTIFICACIONES
# ==========================================
class NotificacionRead(BaseModel):
    id: int
    usuario_id: int
    tipo: str
    ticket_id: Optional[int] = None
    titulo: str
    mensaje: str
    leida: bool
    leida_en: Optional[str] = None
    url: Optional[str] = None
    origen_usuario_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# TICKET EXTENDIDO (nuevos metadatos)
# ==========================================
class TicketMetadataUpdate(BaseModel):
    """Schema para actualizar metadatos extendidos de un ticket."""
    fecha_inicio: Optional[datetime] = None
    fecha_completado: Optional[datetime] = None
    fecha_cumplida: Optional[bool] = None
    portada_color: Optional[str] = None
    portada_adjunto_id: Optional[int] = None
    descripcion_md: Optional[bool] = None
    descripcion: Optional[str] = None
    miembros_ids: Optional[List[int]] = None
    archivado: Optional[bool] = None


# ==========================================
# RESPUESTA DE VISTAS MULTIDIMENSIONALES
# ==========================================
class VistaTablaFila(BaseModel):
    """Fila para la vista de tabla (Excel-like)."""
    id: int
    codigo: str
    titulo: str
    prioridad: str
    estado: str
    estado_color: Optional[str] = None
    asignado: Optional[str] = None
    fecha_vencimiento: Optional[datetime] = None
    etiquetas: List[dict] = []
    progreso: float = 0
    miembros: List[dict] = []
    campos_personalizados: dict = {}
