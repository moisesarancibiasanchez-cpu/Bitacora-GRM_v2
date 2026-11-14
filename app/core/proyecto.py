"""
Contexto de proyecto (multi-tenancy) - V2.009.

Este modulo es la CAPA DE CONTEXTO del aislamiento por proyecto. Por si solo no
cambia nada: expone un ``ContextVar`` con el proyecto activo y las funciones
para fijarlo. El filtro ORM (que vive en ``app/db/session.py``) y las
politicas RLS (que viven en ``app/db/rls.py``) consultan este contexto.

Estado por defecto: AISLADO (apagado)
-------------------------------------
``obtener_proyecto_actual()`` devuelve ``None`` mientras el flag
``AISLAMIENTO_PROYECTO_ACTIVO`` sea ``False`` (valor por defecto). Con el
contexto en ``None``:

* la sesion NO aplica ningun criterio de filtrado;
* no se fija el GUC ``app.proyecto_id``;
* las politicas RLS, aunque existan, no restringen nada.

Por eso el despliegue de V2.009 es **puramente aditivo**: el comportamiento
observable de la aplicacion es identico al de V2.008. Encender el aislamiento
(establecer el contexto en cada peticion) es la ventana **V3 (el corte)**.

Porque se usa ``ContextVar`` y no una variable global, dos peticiones
concurrentes con distinto proyecto no se pisan: cada una lleva su contexto.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional, Type

from app.core.config import settings


#: Proyecto activo de la peticion/credencial actual. ``None`` = sin filtro.
_proyecto_actual: ContextVar[Optional[int]] = ContextVar(
    "grm_proyecto_actual", default=None
)


def obtener_proyecto_actual() -> Optional[int]:
    """
    Devuelve el id del proyecto activo, o ``None`` si el aislamiento esta
    apagado o no hay contexto.

    Devolver ``None`` es lo que mantiene el sistema en su comportamiento
    historico: sin contexto no hay filtro.
    """
    if not settings.AISLAMIENTO_PROYECTO_ACTIVO:
        return None
    return _proyecto_actual.get()


def establecer_proyecto_actual(proyecto_id: Optional[int]) -> object:
    """
    Fija el proyecto activo y devuelve el token de reinicio.

    El token permite deshacer el cambio al final de la peticion. Se puede
    usar como gestor de contexto con ``token = ...`` / ``reset(token)``.
    """
    return _proyecto_actual.set(proyecto_id)


def reiniciar_proyecto_actual() -> None:
    """Deja el contexto sin proyecto activo."""
    _proyecto_actual.set(None)


@contextmanager
def contexto_proyecto(proyecto_id: Optional[int]) -> Iterator[Optional[int]]:
    """
    Gestor de contexto que fija el proyecto activo durante el bloque.

    Al salir restaura el contexto anterior aunque haya excepciones.

    Uso::

        with contexto_proyecto(1):
            ...  # aqui las consultas ven solo el proyecto 1
    """
    token = _proyecto_actual.set(proyecto_id)
    try:
        yield proyecto_id
    finally:
        _proyecto_actual.reset(token)


def clases_con_proyecto() -> List[Type]:
    """
    Devuelve las clases ORM que tienen la columna ``proyecto_id``.

    La lista se DERIVA del metadata de SQLAlchemy en vez de mantenerse a mano:
    asi no puede desincronizarse de los modelos (el mismo motivo por el que
    ``app/api/v1/metricas.py`` deriva las columnas del pivote del catalogo).

    Se usa ``Base.registry.mappers`` (API publica) en vez de
    ``Base.metadata.tables`` porque hacen falta las CLASES (para
    ``with_loader_criteria``), no las tablas.
    """
    from app.db.base import Base

    resultado: List[Type] = []
    for mapper in Base.registry.mappers:
        tabla = mapper.local_table
        if tabla is not None and "proyecto_id" in tabla.c:
            resultado.append(mapper.class_)
    return resultado


def tablas_con_proyecto() -> List[str]:
    """
    Nombres de las tablas de negocio que tienen la columna ``proyecto_id``.

    Se excluyen las tablas PUENTE (las que tienen ``proyecto_id`` como parte de
    su clave primaria, como ``proyecto_usuarios``): no son tablas de datos de
    un proyecto, sino tablas de relacion, y su aislamiento se deriva del de las
    tablas a las que apuntan.
    """
    from app.db.base import Base

    resultado = []
    for nombre, tabla in Base.metadata.tables.items():
        if "proyecto_id" not in tabla.c:
            continue
        if "proyecto_id" in {c.name for c in tabla.primary_key.columns}:
            continue
        resultado.append(nombre)
    return sorted(resultado)
