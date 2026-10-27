"""Regresiones de V2.004: prefijo SOL para los tickets que no son incidencias
y exclusion estructural del bloque de incidencias del dashboard.

Contexto del defecto
--------------------
La regla de codigo de un ticket vivia duplicada en cuatro sitios de creacion
y tres de ellos generaban SIEMPRE ``INC-NNN``, ignorando el tipo:

  * ``app/main.py`` (``POST /tickets/crear``) -> solo ``resultado_pruebas``
    tenia prefijo propio (``GAR_<HU>_<NNN>``); el resto, ``INC-NNN``.
  * ``app/api/v1/tickets.py`` (duplicar) -> siempre ``INC-NNN``.
  * ``app/services/ticket_service.py`` -> siempre ``INC-NNN``.
  * ``app/api/v1/import_export.py`` (importar) -> siempre ``INC-NNN``.

Consecuencia: una Solicitud, un Problema o un Cambio se creaban con codigo
``INC-...``. Como el filtro de incidencias del dashboard
(``app/api/v1/metricas.py::_build_tipo_filter``) acepta el prefijo
``INC-``/``INC_`` ademas del enum ``INCIDENCIA``, esos tickets entraban en la
"Lista de Incidencias Recientes" y en los indicadores de incidencias
("INCIDENCIAS LEVANTADAS", "NUEVAS (7D)", "ABIERTAS", "INCIDENCIAS ABIERTAS",
"Proximos a vencer SLA", "Cuenta de Resultado") aunque su tipo no fuese
incidencia.

Ademas el filtro era fragil por construccion: dependia del prefijo, que es
un dato derivado. Bastaba con que un camino de creacion (duplicar) generara
un ``INC-`` para que un ticket de tipo Resultado de Pruebas apareciera en las
DOS listas del dashboard (Incidencias y Resultados de pruebas).

Que fija esta suite
-------------------
1. El prefijo del codigo depende del TIPO y solo del tipo:
     incidencia         -> ``INC-NNN``
     solicitud/problema/cambio -> ``SOL-NNN``
     resultado_pruebas  -> ``GAR_<HU>_<NNN>``
   y las cuatro rutas de creacion aplican la MISMA regla.
2. Un ticket de tipo Solicitud/Problema/Cambio (o Resultado de Pruebas) NUNCA
   aparece en la "Lista de Incidencias Recientes" ni en los indicadores de
   incidencias, incluso si su codigo es un ``INC-`` (garantia estructural, no
   accidental).

Todos los tests operan sobre la base SQLite temporal de la suite (ver
``tests/conftest.py``): nunca leen ni escriben en la base de datos de
produccion.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CLAVE = "Clave-local-de-regresion-2026"

#: Tipos que no son incidencias y que por tanto llevan prefijo SOL.
TIPOS_SOL = ("solicitud", "problema", "cambio")


# ---------------------------------------------------------------------------
# Utilidades compartidas
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_and_schema():
    """Prepara el esquema en la SQLite temporal de la suite."""
    from app.db.base import Base
    from app.db.session import engine
    from app.main import app

    Base.metadata.create_all(bind=engine)
    return app, engine


@pytest.fixture(scope="module")
def local_client(app_and_schema):
    """Cliente HTTP local con sesion; no abre conexiones de red."""
    app, _engine = app_and_schema
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db_session(app_and_schema):
    """Sesion SQLAlchemy sobre la SQLite temporal de la suite."""
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_con_sesion(local_client, db_session):
    """Administrador autenticado en el cliente HTTP local."""
    from app.core.security import hash_password
    from app.models.usuario import RolUsuario, Usuario

    username = "v2004_admin_sol"
    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        usuario = Usuario(
            username=username,
            email=f"{username}@example.test",
            nombre_completo="Admin V2004",
            hashed_password=hash_password(CLAVE),
            rol=RolUsuario.ADMINISTRADOR,
            is_active=True,
        )
        db_session.add(usuario)
        db_session.commit()
        db_session.refresh(usuario)

    login = local_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": CLAVE},
    )
    assert login.status_code == 200, login.text
    return usuario


@pytest.fixture
def estado_inicial(db_session, admin_con_sesion):
    """Un estado inicial valido para poder crear tickets."""
    from app.models.estado import Estado

    estado = (
        db_session.query(Estado)
        .filter(Estado.es_inicial == True)  # noqa: E712
        .first()
    )
    if estado is None:
        estado = Estado(
            nombre="V2004 Inicial", color="#3b82f6", orden=1, es_inicial=True
        )
        db_session.add(estado)
        db_session.commit()
        db_session.refresh(estado)
    return estado


def _crear_por_endpoint(local_client, tipo, titulo, hu=None):
    """Crea un ticket por el endpoint real de creacion y devuelve el codigo."""
    datos = {
        "titulo": titulo,
        "descripcion": "Ticket creado por la suite de regresion de V2.004.",
        "tipo": tipo,
        "prioridad": "media",
    }
    if hu:
        datos["hu_o_caso_prueba"] = hu
    respuesta = local_client.post("/tickets/crear", data=datos)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta


def _buscar_por_titulo(db_session, titulo):
    """Relee el ticket creado por el endpoint (otra sesion) por su titulo."""
    from app.models.ticket import Ticket

    db_session.rollback()
    db_session.expire_all()
    ticket = (
        db_session.query(Ticket)
        .filter(Ticket.titulo == titulo)
        .order_by(Ticket.id.desc())
        .first()
    )
    assert ticket is not None, "no se encontro el ticket %r" % titulo
    return ticket


def _codigos_de_la_lista(local_client, tipo="incidencia", dias=365):
    """Devuelve los codigos que devuelve la 'Lista de Incidencias Recientes'."""
    respuesta = local_client.get(
        "/api/v1/metricas/incidencias-recientes",
        params={"tipo": tipo, "periodo_dias": dias, "limite": 200},
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    return (
        [t.get("codigo") for t in (cuerpo.get("tickets") or [])],
        cuerpo.get("metricas", {}).get("total_periodo"),
    )


def _indicadores(local_client, dias=365):
    """Devuelve los indicadores de incidencias del dashboard."""
    resumen = local_client.get(
        "/api/v1/metricas/resumen", params={"dias": dias}
    ).json()
    completo = local_client.get(
        "/api/v1/metricas/dashboard-completo", params={"dias": dias}
    ).json()
    return {
        "resumen_total": resumen.get("incidencias", {}).get("total"),
        "resumen_activas": resumen.get("incidencias", {}).get("activas"),
        "resumen_nuevas_7d": resumen.get("incidencias", {}).get("nuevas_7d"),
        "resumen_backlog_7d": resumen.get("incidencias", {}).get("backlog_7d"),
        "completo_total": completo.get("incidencias", {}).get("total"),
    }


# ---------------------------------------------------------------------------
# 1) El prefijo depende del tipo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tipo", TIPOS_SOL)
def test_los_tipos_no_incidencia_se_crean_con_prefijo_sol(
    local_client, db_session, estado_inicial, tipo
):
    """Solicitud, Problema y Cambio se crean con prefijo SOL-."""
    titulo = "V2004 prefijo %s" % tipo
    _crear_por_endpoint(local_client, tipo, titulo)

    ticket = _buscar_por_titulo(db_session, titulo)
    assert ticket.codigo.startswith("SOL-"), (
        "un ticket de tipo %s debe llevar prefijo SOL-, lleva %r"
        % (tipo, ticket.codigo)
    )
    assert ticket.tipo.value == tipo
    assert not ticket.codigo.startswith("INC-")


def test_una_incidencia_sigue_llevando_prefijo_inc(local_client, db_session, estado_inicial):
    """El tipo incidencia NO cambia: sigue con INC-."""
    titulo = "V2004 prefijo incidencia"
    _crear_por_endpoint(local_client, "incidencia", titulo)

    ticket = _buscar_por_titulo(db_session, titulo)
    assert ticket.codigo.startswith("INC-"), ticket.codigo
    assert ticket.tipo.value == "incidencia"


def test_resultado_de_pruebas_sigue_llevando_prefijo_gar(
    local_client, db_session, estado_inicial
):
    """El tipo resultado_pruebas NO cambia: sigue con GAR_<HU>_<NNN>."""
    titulo = "V2004 prefijo resultado_pruebas"
    hu = "SC_V2004_1"
    _crear_por_endpoint(local_client, "resultado_pruebas", titulo, hu=hu)

    ticket = _buscar_por_titulo(db_session, titulo)
    assert ticket.codigo.startswith("GAR_"), ticket.codigo
    assert ticket.codigo.startswith("GAR_SC_V2004_1_"), ticket.codigo
    assert ticket.tipo.value == "resultado_pruebas"


def test_la_familia_sol_tiene_correlativo_propio(
    local_client, db_session, estado_inicial
):
    """Los SOL- no consumen la numeracion de los INC-."""
    titulos = ["V2004 correlativo SOL %d" % i for i in range(2)]
    for titulo in titulos:
        _crear_por_endpoint(local_client, "solicitud", titulo)

    codigos_sol = [_buscar_por_titulo(db_session, t).codigo for t in titulos]
    assert all(c.startswith("SOL-") for c in codigos_sol), codigos_sol
    assert codigos_sol[0] != codigos_sol[1], codigos_sol

    titulo_inc = "V2004 correlativo INC"
    _crear_por_endpoint(local_client, "incidencia", titulo_inc)
    codigo_inc = _buscar_por_titulo(db_session, titulo_inc).codigo
    assert codigo_inc.startswith("INC-"), codigo_inc


# ---------------------------------------------------------------------------
# 2) Los tipos no-incidencia no entran en el bloque de incidencias
# ---------------------------------------------------------------------------
def test_los_tipos_no_incidencia_no_aparecen_en_la_lista_de_incidencias(
    local_client, db_session, estado_inicial
):
    """Un SOL- no sale en la 'Lista de Incidencias Recientes'."""
    codigos = []
    for tipo in TIPOS_SOL:
        titulo = "V2004 lista %s" % tipo
        _crear_por_endpoint(local_client, tipo, titulo)
        codigos.append(_buscar_por_titulo(db_session, titulo).codigo)

    listados, _total = _codigos_de_la_lista(local_client)
    for codigo in codigos:
        assert codigo not in listados, (
            "el ticket %s (tipo no-incidencia) aparece en la lista de incidencias"
            % codigo
        )


def test_crear_tickets_no_incidencia_no_mueve_los_indicadores(
    local_client, db_session, estado_inicial
):
    """Los indicadores de incidencias no cambian al crear Solicitud/Problema/Cambio.

    Esta es la comprobacion de negocio directa: si el contador subiese, los
    tickets estarian sumando como incidencias.
    """
    antes = _indicadores(local_client)
    listados_antes, total_antes = _codigos_de_la_lista(local_client)

    for tipo in TIPOS_SOL:
        _crear_por_endpoint(local_client, tipo, "V2004 indicador %s" % tipo)

    despues = _indicadores(local_client)
    listados_despues, total_despues = _codigos_de_la_lista(local_client)

    for clave in antes:
        assert despues[clave] == antes[clave], (
            "el indicador %s cambio de %s a %s al crear tickets que no son "
            "incidencias" % (clave, antes[clave], despues[clave])
        )
    assert total_despues == total_antes, (
        "el total de la lista de incidencias cambio de %s a %s"
        % (total_antes, total_despues)
    )
    assert len(listados_despues) == len(listados_antes)


def test_un_no_incidencia_con_codigo_inc_tampoco_entra(
    local_client, db_session, estado_inicial
):
    """Garantia estructural: manda el TIPO, no el prefijo.

    Se inyecta a proposito un ticket de tipo Solicitud con codigo 'INC-...' y
    se comprueba que sigue SIN aparecer en la lista de incidencias. Si el
    filtro volviera a depender solo del prefijo, este test fallaria.
    """
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia

    codigo_hostil = "INC-V2004-HOSTIL-001"
    ticket = Ticket(
        codigo=codigo_hostil,
        titulo="V2004 hostil",
        descripcion="Tipo Solicitud con codigo de incidencia, por robustez.",
        tipo=TipoIncidencia.SOLICITUD,
        prioridad=Prioridad.MEDIA,
        estado_id=estado_inicial.id,
        creador_id=admin_creador(db_session).id,
        archivado=False,
    )
    db_session.add(ticket)
    db_session.commit()

    listados, _total = _codigos_de_la_lista(local_client)
    assert codigo_hostil not in listados, (
        "un ticket de tipo Solicitud con codigo %s aparece en la lista de "
        "incidencias: el filtro depende todavia del prefijo" % codigo_hostil
    )


def test_un_resultado_de_pruebas_no_entra_en_la_lista_de_incidencias(
    local_client, db_session, estado_inicial
):
    """Un Resultado de Pruebas tampoco entra en la lista de incidencias.

    Cubre el caso de los tres tickets historicos con prefijo 'INC_' que
    estaban contando en las dos listas del dashboard.
    """
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia

    codigo = "INC_V2004_RP_001"
    ticket = Ticket(
        codigo=codigo,
        titulo="V2004 resultado de pruebas con prefijo INC_",
        descripcion="Tipo Resultado de Pruebas con prefijo historico.",
        tipo=TipoIncidencia.RESULTADO_PRUEBAS,
        prioridad=Prioridad.MEDIA,
        estado_id=estado_inicial.id,
        creador_id=admin_creador(db_session).id,
        hu_o_caso_prueba="SC_V2004_RP",
        archivado=False,
    )
    db_session.add(ticket)
    db_session.commit()

    listados, _total = _codigos_de_la_lista(local_client)
    assert codigo not in listados, (
        "un ticket de tipo Resultado de Pruebas con codigo %s aparece en la "
        "lista de incidencias" % codigo
    )

    # ...pero SI tiene que salir en su propia lista.
    listados_rp, _t = _codigos_de_la_lista(local_client, tipo="resultado_pruebas")
    assert codigo in listados_rp


def test_los_no_incidencia_siguen_siendo_visibles_en_todos_los_tipos(
    local_client, db_session, estado_inicial
):
    """La exclusion es solo del bloque de incidencias: no se pierde nada."""
    titulo = "V2004 visibles"
    _crear_por_endpoint(local_client, "solicitud", titulo)
    codigo = _buscar_por_titulo(db_session, titulo).codigo

    listados_rp, _t1 = _codigos_de_la_lista(local_client, tipo="resultado_pruebas")
    listados_sol, _t2 = _codigos_de_la_lista(local_client, tipo="solicitud")
    listados_todos, _t3 = _codigos_de_la_lista(local_client, tipo="todos")

    assert codigo in listados_sol, codigo
    assert codigo in listados_todos, codigo
    # No debe salir en la lista de resultados de pruebas (su tipo no es ese).
    assert codigo not in listados_rp, codigo


# ---------------------------------------------------------------------------
# 3) Las cuatro rutas de creacion aplican la misma regla
# ---------------------------------------------------------------------------
def test_duplicar_un_ticket_no_incidencia_conserva_la_regla(
    local_client, db_session, estado_inicial
):
    """Duplicar un SOL- produce otro SOL- (y no un INC-)."""
    titulo = "V2004 duplicar solicitud"
    _crear_por_endpoint(local_client, "solicitud", titulo)
    original = _buscar_por_titulo(db_session, titulo)

    respuesta = local_client.post("/api/v1/tickets/%d/duplicar" % original.id)
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"].startswith("SOL-"), cuerpo["codigo"]
    assert cuerpo["tipo"] == "solicitud", cuerpo["tipo"]

    listados, _total = _codigos_de_la_lista(local_client)
    assert cuerpo["codigo"] not in listados


def test_duplicar_un_ticket_de_resultado_de_pruebas_conserva_gar(
    local_client, db_session, estado_inicial
):
    """Duplicar un GAR_ produce otro GAR_ (antes producia un INC-)."""
    titulo = "V2004 duplicar resultado_pruebas"
    _crear_por_endpoint(local_client, "resultado_pruebas", titulo, hu="SC_V2004_2")
    original = _buscar_por_titulo(db_session, titulo)

    respuesta = local_client.post("/api/v1/tickets/%d/duplicar" % original.id)
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"].startswith("GAR_"), cuerpo["codigo"]

    listados, _total = _codigos_de_la_lista(local_client)
    assert cuerpo["codigo"] not in listados


def test_el_servicio_de_tickets_usa_la_misma_regla(
    db_session, admin_con_sesion, estado_inicial
):
    """TicketService.crear_ticket tambien aplica la regla por tipo."""
    from app.services.ticket_service import TicketService

    servicio = TicketService(db_session)
    ticket = servicio.crear_ticket(
        {
            "titulo": "V2004 servicio solicitud",
            "descripcion": "Creado por el servicio.",
            "tipo": "solicitud",
            "prioridad": "media",
        },
        admin_con_sesion,
    )
    assert ticket.codigo.startswith("SOL-"), ticket.codigo
    assert ticket.tipo.value == "solicitud"


def test_la_importacion_usa_la_misma_regla(local_client, db_session, estado_inicial):
    """La importacion de tickets tambien aplica la regla por tipo."""
    contenido = (
        "titulo,descripcion,tipo,prioridad\n"
        "V2004 importado solicitud,Descripcion,solicitud,media\n"
        "V2004 importado incidencia,Descripcion,incidencia,media\n"
    ).encode("utf-8")

    respuesta = local_client.post(
        "/api/v1/tickets-ie/importar/csv",
        files={"archivo": ("tickets.csv", contenido, "text/csv")},
        data={"dry_run": "false"},
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo.get("total_errores", 0) == 0, cuerpo.get("errores")

    db_session.rollback()
    db_session.expire_all()
    solicitud = _buscar_por_titulo(db_session, "V2004 importado solicitud")
    incidencia = _buscar_por_titulo(db_session, "V2004 importado incidencia")
    assert solicitud.codigo.startswith("SOL-"), solicitud.codigo
    assert incidencia.codigo.startswith("INC-"), incidencia.codigo


# ---------------------------------------------------------------------------
# Utilidad auxiliar
# ---------------------------------------------------------------------------
def admin_creador(db_session):
    """Devuelve (o crea) el usuario creador usado por los tickets de prueba."""
    from app.core.security import hash_password
    from app.models.usuario import RolUsuario, Usuario

    username = "v2004_creador_sol"
    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        usuario = Usuario(
            username=username,
            email=f"{username}@example.test",
            nombre_completo="Creador V2004",
            hashed_password=hash_password(CLAVE),
            rol=RolUsuario.ADMINISTRADOR,
            is_active=True,
        )
        db_session.add(usuario)
        db_session.commit()
        db_session.refresh(usuario)
    return usuario
