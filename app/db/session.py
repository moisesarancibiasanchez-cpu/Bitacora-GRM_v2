"""
Sesión de SQLAlchemy: motor + SessionLocal.

V2.009 añade el aislamiento por proyecto en dos piezas:

* ``SesionProyecto``: subclase de ``Session`` que, cuando hay un proyecto
  activo en el contexto (``app/core/proyecto.py``), aplica el criterio de
  filtrado por ``proyecto_id`` a todas las clases que lo llevan, mediante
  ``Session.with_loader_criteria()``. El criterio se aplica a la sesión
  ENTERA, de modo que cubre tanto la API moderna (``select()``) como la
  heredada (``Query``) y también las cargas por relacion (``lazy="select"``).

* El listener ``after_begin``: fija el GUC de sesion ``app.proyecto_id`` en la
  transaccion, que es lo que leen las politicas RLS de PostgreSQL.

Ambas piezas son INERTES mientras no haya contexto de proyecto: en V2.009 el
flag ``AISLAMIENTO_PROYECTO_ACTIVO`` esta apagado, ``obtener_proyecto_actual()``
devuelve ``None`` y, por tanto, no se aplica ningun criterio ni se fija ningun
GUC. El comportamiento observable de la aplicacion no cambia.

El listener se registra sobre la clase ``Session`` (no sobre ``SessionLocal``)
para que cubra TODAS las sesiones de la aplicacion, incluidas las ~25 que
``app/main.py`` abre directamente con ``SessionLocal()`` y las que abre Celery.
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session, with_loader_criteria
from sqlalchemy.sql import true

from app.core.config import settings
from app.core.proyecto import obtener_proyecto_actual


def _build_engine_kwargs():
    url = settings.get_database_url()
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "echo": settings.DEBUG}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20, "echo": settings.DEBUG}


engine = create_engine(settings.get_database_url(), **_build_engine_kwargs())


def _criterio_proyecto(modelo):
    """
    Devuelve el criterio que se aplica a ``modelo`` en cada consulta.

    Se construye con el valor CONCRETO del proyecto activo (no con un
    callable): SQLAlchemy no permite invocar funciones de Python dentro de las
    expresiones lambda que usa internamente ``with_loader_criteria``, asi que
    el valor se lee antes de construir el criterio.

    Sin proyecto activo devuelve ``true()``: no se restringe nada, que es el
    comportamiento historico (V2.008) y el de la ventana V2.009, donde el
    aislamiento esta apagado.
    """
    proyecto_id = obtener_proyecto_actual()
    if proyecto_id is None:
        return true()
    return modelo.proyecto_id == proyecto_id


@event.listens_for(Session, "do_orm_execute")
def _inyectar_filtro_proyecto(orm_execute_state):
    """
    Inyecta el filtro por proyecto en cada consulta ORM.

    Es la via que funciona con la version fijada (SQLAlchemy 2.0.36): el
    listener de clase ``"load"`` con ``with_loader_criteria`` exige un
    callable, y el sistema de lambdas de SQLAlchemy no admite llamadas a
    funciones de Python dentro de el.

    Aqui, en cambio, el criterio se construye con el valor concreto del
    proyecto activo en el momento de la consulta, de modo que:

    * dos peticiones concurrentes con distinto proyecto no se pisan (el valor
      se lee del ``ContextVar`` en cada consulta);
    * el filtro cubre la API moderna (``select``) y la heredada (``Query``),
      porque ``do_orm_execute`` se dispara en ambas;
    * las cargas por relacion (lazy y eager) tambien lo cubren, porque son
      consultas ORM propias.

    Sin proyecto activo no se inyecta nada: el comportamiento es identico al
    de V2.008.
    """
    if not orm_execute_state.is_select:
        return
    if obtener_proyecto_actual() is None:
        return

    from app.core.proyecto import clases_con_proyecto

    sentencia = orm_execute_state.statement
    for modelo in clases_con_proyecto():
        criterio = _criterio_proyecto(modelo)
        if criterio is not None:
            sentencia = sentencia.options(
                with_loader_criteria(modelo, criterio)
            )
    orm_execute_state.statement = sentencia


class SesionProyecto(Session):
    """
    ``Session`` que aplica el filtro de proyecto cuando hay contexto activo.

    Sin contexto (``obtener_proyecto_actual()`` devuelve ``None``) la sesion
    se comporta exactamente como una ``Session`` normal: no se aplica ningun
    criterio. Ese es el estado por defecto de V2.009.

    El filtrado real lo hace el listener global registrado por
    ``registrar_filtro_proyecto()``; esta clase se mantiene como punto de
    extension y para dejar explicito en el codigo que TODAS las sesiones de
    la aplicacion (las ~25 que ``app/main.py`` abre directamente con
    ``SessionLocal()`` y las que abre Celery) son sensibles al aislamiento.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False,
    # OJO: el parametro se llama ``class_``, no ``cls``. En SQLAlchemy 2.0 el
    # ``sessionmaker`` acepta el resto de kwargs y los pasa a
    # ``Session.__init__``, de modo que un ``cls=`` equivocado acaba en el
    # constructor de la Session y revienta con
    # "Session.__init__() got an unexpected keyword argument 'cls'".
    class_=SesionProyecto,
)


@event.listens_for(Session, "after_begin")
def _fijar_proyecto_en_la_transaccion(session, transaction, connection):
    """
    Fija ``app.proyecto_id`` en la transaccion actual.

    Es el canal que usan las politicas RLS de PostgreSQL
    (``current_setting('app.proyecto_id', true)``). Se usa ``set_config`` con
    el ambito de transaccion (``true`` = local), de modo que el valor desaparece
    al terminar la transaccion y no se filtra entre peticiones.

    No hace nada si no hay proyecto activo: sin GUC, las politicas RLS (si
    llegaran a activarse) se comportarian de forma permisiva.
    """
    proyecto_id = obtener_proyecto_actual()
    if proyecto_id is None:
        return
    # ``set_config`` es una funcion de PostgreSQL. En SQLite (dev y tests) no
    # existe, y las politicas RLS tampoco: ahi el GUC no aplica.
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT set_config('app.proyecto_id', :valor, true)"),
        {"valor": str(proyecto_id)},
    )


def get_db() -> Session:
    """Dependencia FastAPI para inyectar una sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
