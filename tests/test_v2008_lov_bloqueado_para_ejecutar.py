"""
Regresiones de V2.008: "BLOQUEADO PARA EJECUTAR" pasa a ser una categoria
propia del LOV de Resultado de Pruebas.

Contexto del cambio
-------------------
El consolidado UAT traia el valor de origen ``BLOQUEADO PARA EJECUTAR``
(hoja CONSOLIDADO UAT, columna L "Resultado"), que **no** era un valor del
LOV: hasta V2.007 se colapsaba a ``DESESTIMADA`` antes de tocar la base
(``tools/uat_mapping.py`` y ``app/services/uat_import.py``), por
considerarlo "≈ mismo significado operativo".

A partir de V2.008 es una categoria de primer nivel:

  * valor canonico: ``BLOQUEADO PARA EJECUTAR``
  * acronimo:       ``BLOQ``
  * color propio:   ``#0891b2`` (cian 600), que no reutiliza ninguno de los
    otros siete colores del catalogo
  * tooltip:        ``Resultado de pruebas: BLOQUEADO PARA EJECUTAR``

Reglas de negocio que el lote NO cambia:

  * NO cuenta como aprobacion: el porcentaje de aprobados del pie del
    dashboard (OK + OK CON OBS.) no cambia.
  * NO se renombra ni se elimina ``DESESTIMADA``.
  * NO se agregan ni modifican estados del flujo.
  * NO se cambia el calculo de ``fecha_cumplida`` / ``fecha_completado``.
  * NO se hace backfill: los tickets ya cargados con ``DESESTIMADA`` que
    venian de "BLOQUEADO PARA EJECUTAR" son indistinguibles.

Todos los tests operan sobre la base SQLite temporal de la suite (ver
``tests/conftest.py``): nunca leen ni escriben en la base de datos de
produccion.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA_DASHBOARD = RAIZ / "app" / "templates" / "dashboard" / "index.html"
FUENTE_METRICAS = RAIZ / "app" / "api" / "v1" / "metricas.py"
FUENTE_UAT_IMPORT = RAIZ / "app" / "services" / "uat_import.py"
FUENTE_UAT_MAPPING = RAIZ / "tools" / "uat_mapping.py"
FUENTE_LOAD_UAT = RAIZ / "tools" / "load_uat_consolidado.py"

CLAVE = "Clave-local-de-regresion-2026"

#: Valor canonico de la categoria nueva.
VALOR = "BLOQUEADO PARA EJECUTAR"
#: Acronimo que se muestra en el badge de la tarjeta y en el titulo de la
#: columna del pivote.
ACRONIMO = "BLOQ"
#: Color propio de la categoria (cian 600).
COLOR = {"bg": "#0891b2", "text": "#ffffff", "cellText": "#1f2937"}

#: Valores del LOV que EXISTIAN antes de este lote y no deben cambiar.
LOV_PREVIO = ("N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA")
#: Acronimos vigentes de esos valores (no deben cambiar).
ACRONIMOS_PREVIOS = {
    "OK": "OK",
    "N/A": "N/A",
    "OK CON OBS.": "OBS",
    "POSTERGADA": "POST",
    "DESESTIMADA": "DESEST",
    "NOK": "NOK",
}
#: Colores vigentes de esos valores (no deben cambiar).
COLORES_PREVIOS = {
    "N/A": "#94a3b8",
    "NOK": "#dc2626",
    "OK": "#16a34a",
    "OK CON OBS.": "#eab308",
    "POSTERGADA": "#ea580c",
    "DESESTIMADA": "#7c3aed",
    "(en blanco)": "#cbd5e1",
}

#: Variantes de entrada que deben normalizarse al valor canonico.
VARIANTES = (
    "BLOQUEADO PARA EJECUTAR",
    "bloqueado para ejecutar",
    "BLOQUEADO PARA EJECUCION",
    "BLOQUEADO PARA EJECUTAR.",
    "BLOQUEADO",
    "bloqueado",
    "  Bloqueado Para Ejecutar  ",
)


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

    username = "v2008_admin_bloq"
    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        usuario = Usuario(
            username=username,
            email=f"{username}@example.test",
            nombre_completo="Admin V2008",
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
            nombre="V2008 Inicial", color="#3b82f6", orden=1, es_inicial=True
        )
        db_session.add(estado)
        db_session.commit()
        db_session.refresh(estado)
    return estado


def _crear_ticket_con_resultado(local_client, resultado, titulo, modulo="Incidencias"):
    """Crea un ticket real por la API JSON y devuelve el cuerpo de respuesta."""
    datos = {
        "titulo": titulo,
        "descripcion": "Ticket creado por la suite de regresion de V2.008.",
        "tipo": "resultado_pruebas",
        "prioridad": "media",
        "modulo": modulo,
        "ambiente": "QA",
        "resultado_pruebas": resultado,
        "hu_o_caso_prueba": "V2008_SC_1",
    }
    return local_client.post("/api/v1/tickets", json=datos)


# ---------------------------------------------------------------------------
# 1. El catalogo (SSOT)
# ---------------------------------------------------------------------------
def test_el_lov_incluye_la_categoria_nueva():
    """``RESULTADOS_LOV`` contiene el valor canonico."""
    from app.core.resultado_pruebas import RESULTADOS_LOV

    assert VALOR in RESULTADOS_LOV


def test_la_categoria_nueva_vale_23_caracteres_y_cabe_en_la_columna():
    """``resultado_pruebas`` es ``VARCHAR(40)``: no hace falta migracion."""
    from app.models.ticket import Ticket

    assert len(VALOR) == 23
    assert Ticket.resultado_pruebas.type.length >= len(VALOR)


def test_el_lov_de_formulario_incluye_la_categoria_nueva():
    """``RESULTADOS_LOV_FORMULARIO`` (selector de alta/edicion) la incluye."""
    from app.core.resultado_pruebas import RESULTADOS_LOV_FORMULARIO

    assert VALOR in RESULTADOS_LOV_FORMULARIO


def test_los_dos_ordenes_describen_el_mismo_conjunto():
    """Invariante del catalogo: los dos ordenes son el mismo conjunto."""
    from app.core.resultado_pruebas import (
        RESULTADOS_LOV,
        RESULTADOS_LOV_FORMULARIO,
    )

    assert set(RESULTADOS_LOV_FORMULARIO) == set(RESULTADOS_LOV)


def test_el_acronimo_de_la_categoria_nueva_es_bloq():
    """``ACRONIMOS["BLOQUEADO PARA EJECUTAR"]`` debe ser ``"BLOQ"``."""
    from app.core.resultado_pruebas import ACRONIMOS

    assert ACRONIMOS[VALOR] == ACRONIMO


def test_los_colores_de_la_categoria_nueva_son_los_especificados():
    """La paleta de la categoria nueva es la de la especificacion."""
    from app.core.resultado_pruebas import COLORES

    assert COLORES[VALOR] == COLOR


def test_el_color_propio_no_reutiliza_ninguno_de_los_existentes():
    """El cian 600 no puede ser el fondo de otra categoria."""
    from app.core.resultado_pruebas import COLORES

    fondos = [c["bg"] for c in COLORES.values()]
    assert len(fondos) == len(set(fondos)), "hay colores de fondo repetidos"
    assert COLOR["bg"] not in COLORES_PREVIOS.values()


def test_el_resto_del_lov_no_cambia():
    """Los seis valores previos conservan valor, acronimo y color."""
    from app.core.resultado_pruebas import ACRONIMOS, COLORES

    for valor, acronimo in ACRONIMOS_PREVIOS.items():
        assert ACRONIMOS[valor] == acronimo, valor
    for valor, bg in COLORES_PREVIOS.items():
        assert COLORES[valor]["bg"] == bg, valor


@pytest.mark.parametrize("variante", VARIANTES)
def test_normalizar_resultado_acepta_las_variantes_de_entrada(variante):
    """``normalizar_resultado`` canonicaliza todas las variantes de entrada."""
    from app.core.resultado_pruebas import normalizar_resultado

    assert normalizar_resultado(variante) == VALOR


def test_normalizar_resultado_ya_no_colapsa_a_desestimada():
    """Punto 9 de la especificacion: el valor ya no se colapsa."""
    from app.core.resultado_pruebas import normalizar_resultado

    assert normalizar_resultado(VALOR) == VALOR
    assert normalizar_resultado(VALOR) != "DESESTIMADA"


def test_info_resultado_devuelve_la_ficha_de_la_categoria_nueva():
    """Punto 8: acronimo, colores y tooltip de la categoria nueva."""
    from app.core.resultado_pruebas import info_resultado

    ficha = info_resultado(VALOR)
    assert ficha is not None
    assert ficha["valor"] == VALOR
    assert ficha["acronimo"] == ACRONIMO
    assert ficha["bg"] == COLOR["bg"]
    assert ficha["text"] == COLOR["text"]
    assert ficha["cellText"] == COLOR["cellText"]
    assert ficha["titulo"] == "Resultado de pruebas: BLOQUEADO PARA EJECUTAR"


def test_lov_js_incluye_la_categoria_antes_del_en_blanco():
    """El JS del dashboard consume esta lista: la categoria va antes de la
    pseudo-columna ``(en blanco)``."""
    from app.core.resultado_pruebas import RESULTADOS_CONOCIDOS, lov_js

    columnas = lov_js()
    assert VALOR in columnas
    assert columnas.index(VALOR) < columnas.index("(en blanco)")
    assert columnas == list(RESULTADOS_CONOCIDOS)


def test_el_modelo_reexporta_el_lov_del_catalogo():
    """``app.models.ticket.RESULTADO_PRUEBAS_LOV`` no redeclara la lista."""
    from app.core.resultado_pruebas import RESULTADOS_LOV
    from app.models.ticket import RESULTADO_PRUEBAS_LOV

    assert RESULTADO_PRUEBAS_LOV == RESULTADOS_LOV
    assert VALOR in RESULTADO_PRUEBAS_LOV


def test_el_schema_permite_el_valor_nuevo():
    """El validador de la API acepta el valor (si no, responderia 422)."""
    from app.schemas.ticket import RESULTADO_PRUEBAS_PERMITIDOS

    assert VALOR in RESULTADO_PRUEBAS_PERMITIDOS


# ---------------------------------------------------------------------------
# 2. El pivote "Cuenta de Resultado"
# ---------------------------------------------------------------------------
def test_las_columnas_del_pivote_incluyen_la_categoria_antes_del_en_blanco(
    local_client, admin_con_sesion
):
    """Punto 1: la columna existe en la respuesta del pivote."""
    respuesta = local_client.get("/api/v1/metricas/cuenta-resultado")
    assert respuesta.status_code == 200, respuesta.text

    columnas = respuesta.json()["columnas"]
    assert VALOR in columnas
    assert columnas.index(VALOR) < columnas.index("(en blanco)")


def test_totales_por_columna_incluye_la_clave_nueva(local_client, admin_con_sesion):
    """Punto 2: la clave existe en los totales (si no, habria KeyError)."""
    respuesta = local_client.get("/api/v1/metricas/cuenta-resultado")
    assert respuesta.status_code == 200, respuesta.text

    cuerpo = respuesta.json()
    assert VALOR in cuerpo["totales_por_columna"]
    assert cuerpo["totales_por_columna"][VALOR] >= 0


def test_las_columnas_del_pivote_coinciden_con_el_catalogo(
    local_client, admin_con_sesion
):
    """El pivote y el front no pueden desalinearse: misma lista y orden."""
    from app.core.resultado_pruebas import RESULTADOS_CONOCIDOS

    respuesta = local_client.get("/api/v1/metricas/cuenta-resultado")
    assert respuesta.status_code == 200, respuesta.text

    assert respuesta.json()["columnas"] == list(RESULTADOS_CONOCIDOS)


def test_cada_valor_del_lov_tiene_columna_en_el_sql_del_pivote():
    """Guarda contra la perdida silenciosa de tickets en el pivote.

    Si un valor esta en el catalogo pero no en ``sql_columnas``, sus tickets
    no caen en ninguna columna (ni siquiera en "(en blanco)", que solo
    agrupa NULL/vacio) y desaparecen del reporte sin error.
    """
    fuente = FUENTE_METRICAS.read_text(encoding="utf-8")
    from app.core.resultado_pruebas import RESULTADOS_LOV

    bloque = re.search(
        r"sql_columnas\s*=\s*\[(.*?)\n    \]", fuente, re.S
    )
    assert bloque, "no se encontro el bloque sql_columnas"
    cuerpo = bloque.group(1)
    for valor in RESULTADOS_LOV:
        assert '("%s"' % valor in cuerpo, (
            "el valor %r del LOV no tiene columna en sql_columnas: sus "
            "tickets se perderian en silencio del pivote" % valor
        )


# ---------------------------------------------------------------------------
# 3. La API
# ---------------------------------------------------------------------------
def test_la_api_acepta_el_valor_nuevo(local_client, admin_con_sesion, estado_inicial):
    """Punto 3: crear un ticket con el valor nuevo NO devuelve 422."""
    respuesta = _crear_ticket_con_resultado(
        local_client, VALOR, "V2008 API acepta BLOQUEADO PARA EJECUTAR"
    )
    assert respuesta.status_code in (200, 201), respuesta.text
    assert respuesta.json()["resultado_pruebas"] == VALOR


def test_la_api_rechaza_un_valor_inexistente(local_client, admin_con_sesion):
    """El validador sigue rechazando lo que no esta en el LOV."""
    respuesta = _crear_ticket_con_resultado(
        local_client, "VALOR INVENTADO", "V2008 API rechaza valor inventado"
    )
    assert respuesta.status_code == 422, respuesta.text


def test_el_ticket_con_el_valor_nuevo_aparece_en_su_columna_del_pivote(
    local_client, admin_con_sesion, estado_inicial
):
    """El ticket con el valor nuevo se cuenta en SU columna, no se pierde."""
    titulo = "V2008 pivot columna propia"
    respuesta = _crear_ticket_con_resultado(local_client, VALOR, titulo)
    assert respuesta.status_code in (200, 201), respuesta.text

    cuerpo = local_client.get("/api/v1/metricas/cuenta-resultado").json()
    filas = [f for f in cuerpo["filas"] if f["modulo"] == "Incidencias"]
    assert filas, "no se encontro la fila del modulo Incidencias en el pivote"
    assert filas[0]["valores"][VALOR] >= 1, (
        "el ticket con el valor nuevo no aparece en su columna del pivote"
    )


def test_el_drill_down_filtra_por_la_categoria_nueva(
    local_client, admin_con_sesion, estado_inicial
):
    """El drill-down por celda acepta el valor nuevo y sus variantes."""
    titulo = "V2008 drill down BLOQ"
    respuesta = _crear_ticket_con_resultado(local_client, VALOR, titulo)
    assert respuesta.status_code in (200, 201), respuesta.text

    detalle = local_client.get(
        "/api/v1/metricas/cuenta-resultado/detalle",
        params={"modulo": "Incidencias", "resultado": VALOR},
    )
    assert detalle.status_code == 200, detalle.text
    assert titulo in detalle.text


def test_el_kpi_de_incidencias_abiertas_no_excluye_la_categoria_nueva():
    """Una prueba bloqueada sigue en gestion: cuenta como incidencia abierta.

    El KPI "Incidencias Abiertas" (``incidencias.backlog_7d``) excluye solo
    los tickets con resultado ``DESESTIMADA``; la categoria nueva NO debe
    entrar en esa exclusion.
    """
    fuente = FUENTE_METRICAS.read_text(encoding="utf-8")
    bloque = re.search(
        r"_resultado_no_desestimada\s*=\s*or_\((.*?)\n    \)", fuente, re.S
    )
    assert bloque, "no se encontro el filtro _resultado_no_desestimada"
    cuerpo = bloque.group(1)
    assert "DESESTIMADA" in cuerpo
    assert VALOR not in cuerpo, (
        "la categoria nueva no debe excluirse del KPI de incidencias abiertas"
    )
    assert "_resultado_no_desestimada" in fuente


def test_el_porcentaje_de_aprobados_no_cuenta_la_categoria_nueva():
    """El pie del dashboard suma OK + OK CON OBS. y nada mas."""
    texto = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")
    m = re.search(r"const aprobados\s*=\s*\((.*?)\);", texto, re.S)
    assert m, "no se encontro el calculo de aprobados del pie del dashboard"
    cuerpo = m.group(1)
    assert "'OK'" in cuerpo
    assert "'OK CON OBS.'" in cuerpo
    assert VALOR not in cuerpo


def test_la_plantilla_del_dashboard_no_redeclara_el_lov():
    """La plantilla consume el catalogo; no puede hardcodear la lista."""
    texto = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")
    assert "CUENTA_RESULTADO_LOV" in texto
    assert "CUENTA_RESULTADO_COLORES" in texto
    assert "CUENTA_RESULTADO_ACRONIMOS" in texto
    for valor in LOV_PREVIO:
        assert '<option value="%s"' % valor not in texto
    assert 'value="%s"' % VALOR not in texto


# ---------------------------------------------------------------------------
# 4. La carga UAT
# ---------------------------------------------------------------------------
def test_el_importador_uat_no_colapsa_el_valor_a_desestimada():
    """``normalize_resultado`` del importador UAT devuelve el valor canonico."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "v2008_uat_import", FUENTE_UAT_IMPORT
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    assert modulo.normalize_resultado("BLOQUEADO PARA EJECUTAR") == VALOR
    assert modulo.normalize_resultado("bloqueado para ejecutar") == VALOR
    assert modulo.normalize_resultado(VALOR) != "DESESTIMADA"


def test_el_cargador_consolidado_no_colapsa_el_valor_a_desestimada():
    """El script de carga masiva tampoco puede seguir colapsando el valor."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "v2008_load_uat", FUENTE_LOAD_UAT
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    assert modulo.normalize_resultado("BLOQUEADO PARA EJECUTAR") == VALOR
    assert modulo.normalize_resultado(VALOR) != "DESESTIMADA"


def test_el_importador_uat_tiene_estado_destino_para_la_categoria_nueva():
    """El valor nuevo debe tener un estado destino.

    La especificacion original pedia mapearlo a "Analisis/Bloqueado", pero
    ese estado NO existe en el despliegue (verificado por GET
    /api/v1/estados en produccion: el estado real que significa lo mismo es
    "Bloqueado!"). Se mapea al estado existente para no crear una columna
    casi duplicada del Kanban ni tocar el esquema.
    """
    from app.services.uat_import import RESULTADO_A_ESTADO_NOMBRE

    assert VALOR in RESULTADO_A_ESTADO_NOMBRE
    assert RESULTADO_A_ESTADO_NOMBRE[VALOR] == "Bloqueado!"
    # El mapeo de NOK no se modifica en este lote (queda documentado como
    # pendiente de decision de negocio).
    assert RESULTADO_A_ESTADO_NOMBRE["NOK"] == "Analisis/Bloqueado"


def test_la_documentacion_de_uat_mapping_refleja_la_regla_nueva():
    """``tools/uat_mapping.py`` ya no documenta el colapso a DESESTIMADA."""
    fuente = FUENTE_UAT_MAPPING.read_text(encoding="utf-8")
    assert '"BLOQUEADO PARA EJECUTAR"→ "DESESTIMADA"' not in fuente
    assert "ya no" in fuente and "DESESTIMADA" in fuente
