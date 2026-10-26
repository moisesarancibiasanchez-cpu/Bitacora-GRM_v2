"""Regresiones de V2.002: consistencia entre el resumen de la "Lista de
Incidencias Recientes" y su modal de drill-down.

Contexto del defecto
--------------------
La franja de 7 KPI de la seccion "Lista de Incidencias Recientes" muestra
el total del periodo (por ejemplo 18 tickets en 90 dias), pero al hacer
clic en la casilla "Total periodo" el modal listaba solo 2 tickets.

Causa raiz: el modal NO heredaba los filtros de la seccion.

  * El backend ``/api/v1/metricas/detalle-kpi`` solo aceptaba
    ``periodo_dias``; ignoraba ``fecha_desde`` / ``fecha_hasta``, que son
    los que el resumen usa con precedencia cuando el operador elige un
    rango explicito de fechas.
  * El front del modal tomaba el periodo del selector GLOBAL '#periodo'
    (30 dias por defecto) en vez del bloque de la seccion, y leia un id de
    selector de tipo inexistente ('incidencias-tipo' en vez de
    'incidencias-recientes-tipo'), por lo que el tipo siempre caia en
    'incidencia'.

El criterio que fija esta suite es uno solo: **para los mismos filtros,
la cifra del resumen, la cifra del modal y el conteo real en la base tienen
que ser la misma**.

Todos los tests operan sobre la base SQLite temporal de la suite (ver
``tests/conftest.py``): nunca leen ni escriben en la base de datos de
produccion.
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA_DASHBOARD = RAIZ / "app" / "templates" / "dashboard" / "index.html"

CLAVE = "Clave-local-de-regresion-2026"


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

    username = "v2002_admin_kpi"
    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        usuario = Usuario(
            username=username,
            email=f"{username}@example.test",
            nombre_completo="Admin V2002",
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
def estado_y_usuario(db_session, admin_con_sesion):
    """Un estado y un usuario creador para poder crear tickets validos."""
    from app.models.estado import Estado

    estado = db_session.query(Estado).filter(Estado.nombre == "En desarrollo").first()
    if estado is None:
        estado = Estado(nombre="En desarrollo", color="#3b82f6", orden=1)
        db_session.add(estado)
        db_session.commit()
        db_session.refresh(estado)
    return estado, admin_con_sesion


def _crear_ticket(db_session, estado, creador, codigo, created_at, **kwargs):
    """Crea un ticket con fecha de creacion controlada y lo devuelve."""
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia

    ticket = Ticket(
        codigo=codigo,
        titulo=kwargs.get("titulo", f"Ticket de prueba {codigo}"),
        descripcion="Ticket creado por la suite de regresion de V2.002.",
        tipo=kwargs.get("tipo", TipoIncidencia.INCIDENCIA),
        prioridad=kwargs.get("prioridad", Prioridad.MEDIA),
        estado_id=estado.id,
        creador_id=creador.id,
        asignado_id=kwargs.get("asignado_id"),
        created_at=created_at,
        fecha_vencimiento_sla=kwargs.get("fecha_vencimiento_sla"),
        fecha_completado=kwargs.get("fecha_completado"),
        sla_cumplido=kwargs.get("sla_cumplido", 1),
        archivado=kwargs.get("archivado", False),
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)
    return ticket


def _contar_incidencias(db_session, desde, hasta):
    """Conteo INDEPENDIENTE de las incidencias en un rango.

    Reproduce la semantica documentada del filtro 'incidencia' (tipo
    INCIDENCIA o codigo con prefijo INC-) sin usar el helper del
    aplicativo, para que la comparacion sea una comprobacion real y no una
    tautologia.
    """
    from sqlalchemy import or_

    from app.models.ticket import Ticket, TipoIncidencia

    return (
        db_session.query(Ticket.id)
        .filter(
            Ticket.archivado == False,  # noqa: E712
            or_(
                Ticket.tipo == TipoIncidencia.INCIDENCIA,
                Ticket.codigo.like("INC-%"),
                Ticket.codigo.like("INC\\_%", escape="\\"),
            ),
            Ticket.created_at >= desde,
            Ticket.created_at <= hasta,
        )
        .count()
    )


def _rango(desde_dias, hasta_dias, ahora):
    """Devuelve (fecha_desde, fecha_hasta) en formato ISO para la API."""
    return (
        (ahora - timedelta(days=desde_dias)).strftime("%Y-%m-%d"),
        (ahora + timedelta(days=hasta_dias)).strftime("%Y-%m-%d"),
    )


# ---------------------------------------------------------------------------
# 1. El modal respeta el rango explicito de fechas
# ---------------------------------------------------------------------------
def test_el_modal_respeta_el_rango_explicito_de_fechas(
    local_client, db_session, estado_y_usuario
):
    """Con rango explicito, el modal lista los tickets ESE rango.

    Este es el defecto reportado: el modal ignoraba 'fecha_desde' /
    'fecha_hasta' y se quedaba con la ventana de 'periodo_dias'.
    """
    from app.core.timezone import now_utc

    estado, creador = estado_y_usuario
    ahora = now_utc()

    # Tres tickets de hace 45 dias (fuera de la ventana de 30 dias) y uno
    # de hace 5 dias (dentro).
    antiguos = [
        _crear_ticket(db_session, estado, creador, "INC-V2002-ANTIGUO-1", ahora - timedelta(days=45)),
        _crear_ticket(db_session, estado, creador, "INC-V2002-ANTIGUO-2", ahora - timedelta(days=45)),
    ]
    _crear_ticket(db_session, estado, creador, "INC-V2002-RECIENTE-1", ahora - timedelta(days=5))

    desde, hasta = _rango(90, 1, ahora)
    params = {
        "kpi": "total_periodo",
        "tipo": "incidencia",
        "periodo_dias": 30,   # el que el front mandaba antes
        "fecha_desde": desde,
        "fecha_hasta": hasta,
        "limite": 200,
    }

    respuesta = local_client.get("/api/v1/metricas/detalle-kpi", params=params)
    assert respuesta.status_code == 200, respuesta.text
    detalle = respuesta.json()

    codigos = {t["codigo"] for t in detalle["tickets"]}
    for ticket in antiguos:
        assert ticket.codigo in codigos, (
            "el modal no lista %s, que está dentro del rango 90 días" % ticket.codigo
        )

    # Y el total del modal debe incluir los tickets del rango, no los de la
    # ventana de 30 dias.
    ventana_30 = local_client.get(
        "/api/v1/metricas/detalle-kpi",
        params={
            "kpi": "total_periodo",
            "tipo": "incidencia",
            "periodo_dias": 30,
            "limite": 200,
        },
    ).json()

    assert detalle["total"] > ventana_30["total"], (
        "el modal sigue contando la ventana de %s días en vez del rango explícito"
        % ventana_30["total"]
    )


def test_el_modal_y_el_resumen_coinciden_con_el_mismo_rango(
    local_client, db_session, estado_y_usuario
):
    """Resumen, modal y conteo real en base devuelven la MISMA cifra."""
    from app.core.timezone import now_utc

    estado, creador = estado_y_usuario
    ahora = now_utc()

    _crear_ticket(db_session, estado, creador, "INC-V2002-COINCIDE-1", ahora - timedelta(days=45))
    _crear_ticket(db_session, estado, creador, "INC-V2002-COINCIDE-2", ahora - timedelta(days=45))
    _crear_ticket(db_session, estado, creador, "INC-V2002-COINCIDE-3", ahora - timedelta(days=5))

    desde, hasta = _rango(90, 1, ahora)
    params_comunes = {"tipo": "incidencia", "periodo_dias": 30}

    resumen = local_client.get(
        "/api/v1/metricas/incidencias-recientes",
        params={
            **params_comunes,
            "fecha_desde": desde,
            "fecha_hasta": hasta,
            "limite": 200,
        },
    ).json()
    detalle = local_client.get(
        "/api/v1/metricas/detalle-kpi",
        params={
            "kpi": "total_periodo",
            **params_comunes,
            "fecha_desde": desde,
            "fecha_hasta": hasta,
            "limite": 200,
        },
    ).json()

    esperado = _contar_incidencias(
        db_session,
        ahora - timedelta(days=90),
        ahora + timedelta(days=1),
    )

    total_resumen = resumen["metricas"]["total_periodo"]
    total_modal = detalle["total"]

    assert total_resumen == esperado, (
        "el resumen cuenta %s y la base tiene %s" % (total_resumen, esperado)
    )
    assert total_modal == esperado, (
        "el modal cuenta %s y la base tiene %s" % (total_modal, esperado)
    )
    assert total_modal == total_resumen, (
        "el modal (%s) y el resumen (%s) no coinciden" % (total_modal, total_resumen)
    )


def test_el_modal_respeta_la_fecha_hasta_inclusiva(
    local_client, db_session, estado_y_usuario
):
    """Un ticket creado el mismo dia de 'fecha_hasta' entra; al dia siguiente no."""
    from app.core.timezone import now_utc

    estado, creador = estado_y_usuario
    ahora = now_utc()

    # El rango termina hace 40 dias (a una hora de la tarde UTC).
    corte = ahora - timedelta(days=40)

    dentro = _crear_ticket(
        db_session, estado, creador, "INC-V2002-HASTA-DENTRO", corte - timedelta(hours=2)
    )
    borde = _crear_ticket(
        db_session, estado, creador, "INC-V2002-HASTA-BORDE", corte - timedelta(minutes=1)
    )
    fuera = _crear_ticket(
        db_session, estado, creador, "INC-V2002-HASTA-FUERA", corte + timedelta(days=1)
    )

    desde = (ahora - timedelta(days=90)).strftime("%Y-%m-%d")
    hasta = corte.strftime("%Y-%m-%d")

    detalle = local_client.get(
        "/api/v1/metricas/detalle-kpi",
        params={
            "kpi": "total_periodo",
            "tipo": "incidencia",
            "periodo_dias": 90,
            "fecha_desde": desde,
            "fecha_hasta": hasta,
            "limite": 200,
        },
    ).json()

    codigos = {t["codigo"] for t in detalle["tickets"]}
    assert dentro.codigo in codigos
    # El ticket del mismo dia de 'fecha_hasta' entra: el corte es inclusivo
    # contra el final del dia.
    assert borde.codigo in codigos
    # El del dia siguiente queda fuera.
    assert fuera.codigo not in codigos


# ---------------------------------------------------------------------------
# 2. El total del modal es el real, no el truncado por 'limite'
# ---------------------------------------------------------------------------
def test_el_total_del_modal_es_el_real_y_no_el_truncado(
    local_client, db_session, estado_y_usuario
):
    """'total' es el total real del KPI; 'limite' solo recorta el listado."""
    from app.core.timezone import now_utc

    estado, creador = estado_y_usuario
    ahora = now_utc()

    for i in range(3):
        _crear_ticket(
            db_session, estado, creador, "INC-V2002-TRUNCA-%d" % i, ahora - timedelta(days=45)
        )

    detalle = local_client.get(
        "/api/v1/metricas/detalle-kpi",
        params={
            "kpi": "total_periodo",
            "tipo": "incidencia",
            "periodo_dias": 90,
            "limite": 2,
        },
    ).json()

    assert detalle["total_listado"] == 2, detalle
    assert detalle["truncado"] is True, detalle
    assert detalle["total"] > detalle["total_listado"], (
        "el total debe ser el real, no el numero de filas devueltas: %r" % detalle
    )


# ---------------------------------------------------------------------------
# 3. Cada KPI cuadra entre el resumen y el modal
# ---------------------------------------------------------------------------
def test_cada_kpi_cuadra_entre_el_resumen_y_el_modal(
    local_client, db_session, estado_y_usuario
):
    """Los KPI que son un conteo deben dar la misma cifra en ambos sitios."""
    from app.core.timezone import now_utc
    from app.models.ticket import Prioridad

    estado, creador = estado_y_usuario
    ahora = now_utc()

    # Uno vencido, uno en riesgo 72h, uno critico y uno de prioridad alta.
    _crear_ticket(
        db_session, estado, creador, "INC-V2002-KPI-VENCIDA", ahora - timedelta(days=45),
        fecha_vencimiento_sla=ahora - timedelta(days=10),
    )
    _crear_ticket(
        db_session, estado, creador, "INC-V2002-KPI-RIESGO", ahora - timedelta(days=45),
        fecha_vencimiento_sla=ahora + timedelta(days=2),
    )
    _crear_ticket(
        db_session, estado, creador, "INC-V2002-KPI-CRITICA", ahora - timedelta(days=45),
        prioridad=Prioridad.CRITICA,
    )
    _crear_ticket(
        db_session, estado, creador, "INC-V2002-KPI-ALTA", ahora - timedelta(days=45),
        prioridad=Prioridad.ALTA,
    )

    desde, hasta = _rango(90, 1, ahora)
    resumen = local_client.get(
        "/api/v1/metricas/incidencias-recientes",
        params={
            "tipo": "incidencia",
            "periodo_dias": 30,
            "fecha_desde": desde,
            "fecha_hasta": hasta,
            "limite": 200,
        },
    ).json()["metricas"]

    correspondencias = {
        "total_periodo": "total_periodo",
        "vencidas": "vencidas",
        "en_riesgo_72h": "en_riesgo_72h",
        "criticas_o_altas": "criticas_o_altas",
    }

    for kpi, metrica in correspondencias.items():
        detalle = local_client.get(
            "/api/v1/metricas/detalle-kpi",
            params={
                "kpi": kpi,
                "tipo": "incidencia",
                "periodo_dias": 30,
                "fecha_desde": desde,
                "fecha_hasta": hasta,
                "limite": 200,
            },
        ).json()
        assert detalle["total"] == resumen[metrica], (
            "el KPI %s: el resumen dice %s y el modal dice %s"
            % (kpi, resumen[metrica], detalle["total"])
        )


# ---------------------------------------------------------------------------
# 4. El front usa un unico resolvedor de filtros
# ---------------------------------------------------------------------------
def test_el_front_usa_un_resolvedor_unico_de_filtros():
    """El modal no puede resolver los filtros por su cuenta."""
    plantilla = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")

    # El id correcto del selector de tipo de la seccion.
    assert "incidencias-recientes-tipo" in plantilla
    # Y que el id inexistente 'incidencias-tipo' no se use en ningun sitio.
    assert "safeId('incidencias-tipo')" not in plantilla, (
        "el modal lee un selector de tipo inexistente ('incidencias-tipo')"
    )
    # El modal debe usar el resolvedor compartido.
    assert "function _filtrosIncidenciasRecientes()" in plantilla
    assert "_filtrosIncidenciasRecientes()" in plantilla
    # Y debe enviar el rango explicito al backend.
    assert "fecha_desde=" in plantilla
    assert "fecha_hasta=" in plantilla


def test_el_modal_muestra_el_rango_real_y_avisa_del_truncamiento():
    """El modal dice el rango con el que se calculo y avisa si recorta."""
    plantilla = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")

    assert "function _kpiRangoTexto(data)" in plantilla
    assert "_kpiRangoTexto(data)" in plantilla
    assert "data.truncado" in plantilla


def test_el_bloque_hoy_cubre_un_solo_dia():
    """La opcion 'Hoy' del bloque rapido no puede ampliarse a 7 dias."""
    plantilla = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")

    # Debe existir el caso explicito para 'hoy' con 0 dias de antelacion.
    patron = re.compile(r"val\s*===\s*'hoy'")
    assert patron.search(plantilla), "el bloque rápido no distingue la opción 'hoy'"
    bloque_hoy = re.search(r"val\s*===\s*'hoy'[^}]*?dias\s*=\s*0", plantilla, re.S)
    assert bloque_hoy, "la opción 'hoy' debe fijar 0 días de antelación"


def test_la_edicion_manual_de_fechas_no_se_descarta():
    """Escribir una fecha a mano cambia el bloque a 'Personalizado'."""
    plantilla = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")

    assert "function aplicarFechasManuales()" in plantilla
    assert "window.aplicarFechasManuales" in plantilla
    # Los inputs de fecha ya no deben llamar a aplicarBloqueFechas(), que
    # reponia las fechas del bloque rapido.
    inputs_fecha = re.findall(
        r'id="incidencias-recientes-(?:desde|hasta)"[\s\S]{0,160}?onchange="([^"]+)"',
        plantilla,
    )
    assert inputs_fecha, "no se encontraron los inputs de fecha de la sección"
    for handler in inputs_fecha:
        assert handler == "aplicarFechasManuales()", (
            "el input de fecha sigue llamando a %s (descarta la edición manual)" % handler
        )
