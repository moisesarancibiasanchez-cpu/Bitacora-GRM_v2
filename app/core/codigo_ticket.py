"""
Regla única de generación del código de un ticket (SSOT).

Este módulo es la **única fuente de verdad** del prefijo y del correlativo
del código de un ticket, y de qué tipos son considered "incidencia" a efectos
de negocio.

Reglas
------
=====================  =========================  ==============================
Tipo                   Código                     Observaciones
=====================  =========================  ==============================
``incidencia``         ``INC-NNN``                Correlativo por id máximo.
                                                 Es el único tipo que cuenta
                                                 como incidencia en el
                                                 dashboard.
``solicitud``          ``SOL-NNN``                Familia propia, correlativo
``problema``           ``SOL-NNN``                compartido entre los tres
``cambio``             ``SOL-NNN``                tipos no-incidencia.
``resultado_pruebas``  ``GAR_<HU>_<NNN>``         Correlativo 3 dígitos por
                                                 HU (truncada a 12 caracteres
                                                 por el VARCHAR(20) del modelo).
=====================  =========================  ==============================

Por qué centralizarlo
---------------------
Antes de este módulo la regla estaba repartida en cuatro sitios que la
reimplementaban cada uno a su manera:

  * ``app/main.py`` (``POST /tickets/crear``),
  * ``app/api/v1/tickets.py`` (duplicar ticket),
  * ``app/services/ticket_service.py`` (``_generar_codigo_ticket``),
  * ``app/api/v1/import_export.py`` (importación).

Los tres últimos generaban SIEMPRE ``INC-NNN``, ignorando el tipo. Eso
significaba que una Solicitud, un Problema o un Cambio se creaban con
código ``INC-...``, y como el filtro de incidencias del dashboard
(``app/api/v1/metricas.py::_build_tipo_filter``) también acepta el
prefijo ``INC-``/``INC_``, esos tickets entraban en la "Lista de Incidencias
Recientes" y en los indicadores de incidencias del dashboard aunque su tipo
no fuese incidencia.

Con este módulo, los cuatro caminos consumen la misma regla y el prefijo
deja de depender del sitio por el que se crea el ticket.

Además el módulo publica ``TIPOS_NO_INCIDENCIA`` y ``es_tipo_no_incidencia``,
que son los que usa el filtro del dashboard para garantizar
estructuralmente que un ticket de tipo Solicitud/Problema/Cambio (o de
tipo Resultado de Pruebas) NUNCA aparece en el bloque de incidencias.
"""

from __future__ import annotations

from typing import Optional

# --------------------------------------------------------------------------
# Prefijos
# --------------------------------------------------------------------------

#: Prefijo de las incidencias (tipo ``incidencia``).
PREFIJO_INCIDENCIA = "INC-"

#: Prefijo de la familia de tickets que NO son incidencias
#: (tipo ``solicitud``, ``problema`` o ``cambio``).
PREFIJO_SOLICITUD = "SOL-"

#: Prefijo de los tickets de tipo ``resultado_pruebas``.
PREFIJO_RESULTADO_PRUEBAS = "GAR_"

#: Separador entre la HU y el correlativo en el formato ``GAR_<HU>_<NNN>``.
SEPARADOR_GAR = "_"

#: Longitud máxima de la HU dentro del código ``GAR_`` (VARCHAR(20) del modelo:
#: ``GAR_`` = 4 + ``_NNN`` = 4 → quedan 12 caracteres para la HU).
MAX_HU_EN_CODIGO = 12

#: Intentos de asignar un correlativo libre antes de declarar conflicto.
MAX_INTENTOS_NUMERACION = 5

#: Nombres de los tipos (valores realmente almacenados en la columna
#: ``tickets.tipo``) que NO son incidencias. Es la lista que usa el filtro del
#: dashboard (``app/api/v1/metricas.py``) para garantizar estructuralmente
#: que un ticket de estos tipos nunca aparece en el bloque de incidencias.
NOMBRES_TIPOS_NO_INCIDENCIA = (
    "SOLICITUD",
    "PROBLEMA",
    "CAMBIO",
    "RESULTADO_PRUEBAS",
)


# --------------------------------------------------------------------------
# Excepciones
# --------------------------------------------------------------------------

class HuRequeridaError(ValueError):
    """El tipo ``resultado_pruebas`` exige el campo HU o Caso de Prueba."""

    def __init__(self, mensaje: str = "Falta HU o Caso de Prueba"):
        super().__init__(mensaje)
        self.mensaje = mensaje


class ConflictoNumeracionError(RuntimeError):
    """No se pudo asignar un correlativo libre tras varios intentos."""

    def __init__(self, mensaje: str = "Conflicto de numeracion"):
        super().__init__(mensaje)
        self.mensaje = mensaje


# --------------------------------------------------------------------------
# Tipos
# --------------------------------------------------------------------------

def _normalizar_tipo(tipo):
    """Devuelve el ``TipoIncidencia`` correspondiente, o ``None`` si no existe."""
    from app.models.ticket import TipoIncidencia

    if tipo is None:
        return None
    if isinstance(tipo, TipoIncidencia):
        return tipo
    try:
        return TipoIncidencia(str(tipo).strip().lower())
    except ValueError:
        return None


def tipos_no_incidencia() -> tuple:
    """Tipos de ticket que NUNCA deben contar como incidencia."""
    from app.models.ticket import TipoIncidencia

    return (
        TipoIncidencia.SOLICITUD,
        TipoIncidencia.PROBLEMA,
        TipoIncidencia.CAMBIO,
        TipoIncidencia.RESULTADO_PRUEBAS,
    )


def es_tipo_no_incidencia(tipo) -> bool:
    """True si el tipo NO es una incidencia a efectos del dashboard."""
    enum = _normalizar_tipo(tipo)
    if enum is None:
        return False
    return enum in tipos_no_incidencia()


# --------------------------------------------------------------------------
# Generación
# --------------------------------------------------------------------------

def _generar_codigo_inc(db) -> str:
    """``INC-NNN``: correlativo basado en el id máximo de la tabla."""
    from sqlalchemy import func

    from app.models.ticket import Ticket

    ultimo = db.query(func.max(Ticket.id)).scalar() or 0
    return f"{PREFIJO_INCIDENCIA}{(ultimo + 1):03d}"


def _generar_codigo_sol(db) -> str:
    """``SOL-NNN``: correlativo propio de la familia no-incidencia.

    El correlativo es compartido por los tres tipos de la familia
    (Solicitud, Problema y Cambio) y cuenta los tickets ya existentes de
    esa familia, de modo que la numeración no se solapa con la de
    ``INC-`` ni depende del id de la fila.
    """
    from sqlalchemy import func

    from app.models.ticket import Ticket

    count_prev = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.tipo.in_(tipos_no_incidencia()[:3]))
        .scalar()
        or 0
    )
    for offset in range(MAX_INTENTOS_NUMERACION):
        numero = count_prev + 1 + offset
        candidato = f"{PREFIJO_SOLICITUD}{numero:03d}"
        existe = (
            db.query(Ticket).filter(Ticket.codigo == candidato).first()
        )
        if not existe:
            return candidato
    raise ConflictoNumeracionError(
        "No se pudo asignar un correlativo libre para la familia %s"
        % PREFIJO_SOLICITUD
    )


def _generar_codigo_gar(db, hu_o_caso_prueba: str) -> str:
    """``GAR_<HU>_<NNN>``: correlativo 3 dígitos por HU."""
    from sqlalchemy import func

    from app.models.ticket import Ticket, TipoIncidencia

    count_prev = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.tipo == TipoIncidencia.RESULTADO_PRUEBAS,
            Ticket.hu_o_caso_prueba == hu_o_caso_prueba,
        )
        .scalar()
        or 0
    )
    hu_trunc = (hu_o_caso_prueba or "")[:MAX_HU_EN_CODIGO]
    for offset in range(MAX_INTENTOS_NUMERACION):
        numero = count_prev + 1 + offset
        candidato = "%s%s%s%03d" % (
            PREFIJO_RESULTADO_PRUEBAS, hu_trunc, SEPARADOR_GAR, numero
        )
        existe = (
            db.query(Ticket).filter(Ticket.codigo == candidato).first()
        )
        if not existe:
            return candidato
    raise ConflictoNumeracionError(
        "No se pudo asignar un correlativo libre para la HU %s" % hu_o_caso_prueba
    )


def generar_codigo_ticket(db, tipo, hu_o_caso_prueba: Optional[str] = None) -> str:
    """Genera el código de un ticket según su tipo.

    Es la única puerta de entrada: todas las rutas de creación deben pasar
    por aquí para que el prefijo no dependa del camino usado.

    Args:
        db: sesión de SQLAlchemy.
        tipo: ``TipoIncidencia`` o su valor de texto (``"incidencia"``,
            ``"solicitud"``, ``"problema"``, ``"cambio"``,
            ``"resultado_pruebas"``).
        hu_o_caso_prueba: HU o caso de prueba. Obligatorio (y solo usado)
            cuando el tipo es ``resultado_pruebas``.

    Returns:
        El código generado.

    Raises:
        HuRequeridaError: si el tipo es ``resultado_pruebas`` y falta la HU.
        ConflictoNumeracionError: si no se encuentra un correlativo libre.
    """
    enum = _normalizar_tipo(tipo)
    from app.models.ticket import TipoIncidencia

    if enum == TipoIncidencia.RESULTADO_PRUEBAS:
        if not hu_o_caso_prueba:
            raise HuRequeridaError()
        return _generar_codigo_gar(db, hu_o_caso_prueba)

    if enum in (TipoIncidencia.SOLICITUD, TipoIncidencia.PROBLEMA,
                TipoIncidencia.CAMBIO):
        return _generar_codigo_sol(db)

    return _generar_codigo_inc(db)
