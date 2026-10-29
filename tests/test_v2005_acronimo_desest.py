"""
Regresiones de V2.005: la columna de casos DESESTIMADA se titula "DESEST".

Contexto del defecto
--------------------
En la seccion "Cuenta de Resultado" del Dashboard, el encabezado de la
columna de casos **DESESTIMADA** se titulaba ``NOOK`` (nombre heredado de
la hoja UAT). Ese titulo se confundia con el resultado ``NOK`` (no
conforme), que es una categoria **distinta** del LOV y que sigue
mostrando su propio acronimo ``NOK`` y su propio color (rojo).

Causa raiz
----------
El titulo de cada columna de la tabla es el ACRONIMO del valor del LOV, y
ese acronimo lo define el catalogo `app/core/resultado_pruebas.py`
(``ACRONIMOS``), donde el valor para ``"DESESTIMADA"`` era ``"NOOK"``.
La plantilla del dashboard NO redeclara el mapa: lo lee del JSON que
inyecta el servidor, de modo que el titulo se corregia en un unico sitio.

Alcance del lote
----------------
Es un cambio EXCLUSIVAMENTE de presentacion. No se modifica:

  * el valor del LOV (``DESESTIMADA``),
  * la clave de la paleta ni sus colores (violeta ``#7c3aed``),
  * el nombre de la columna en el pivote ni en el drill-down (sigue siendo
    el valor del LOV, que es lo que viaja en el parametro ``resultado``),
  * ningun dato, ni la numeracion de tickets, ni el motor de busqueda.

Todos los tests operan sobre la base SQLite temporal de la suite (ver
``tests/conftest.py``): nunca leen ni escriben en la base de datos de
produccion.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA_DASHBOARD = RAIZ / "app" / "templates" / "dashboard" / "index.html"
FUENTE_METRICAS = RAIZ / "app" / "api" / "v1" / "metricas.py"

CLAVE = "Clave-local-de-regresion-2026"

#: Valor del LOV (NO cambia en este lote).
VALOR_LOV = "DESESTIMADA"
#: Acronimo vigente del valor del LOV.
ACRONIMO_NUEVO = "DESEST"
#: Acronimo heredado que ya no debe aparecer por ningun lado.
ACRONIMO_VIEJO = "NOOK"

#: Color canonico de la categoria DESESTIMADA (violeta). No debe cambiar.
COLOR_DESESTIMADA = {
    "bg": "#7c3aed",
    "text": "#ffffff",
    "cellText": "#1f2937",
}


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

    username = "v2005_admin_desest"
    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        usuario = Usuario(
            username=username,
            email=f"{username}@example.test",
            nombre_completo="Admin V2005",
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


def _texto_plantilla():
    return PLANTILLA_DASHBOARD.read_text(encoding="utf-8")


def _json_inyectado(html: str, element_id: str):
    """Extrae el JSON que el servidor inyecta en un <script> de la plantilla."""
    patron = (
        r'<script id="%s" type="application/json">(.*?)</script>' % re.escape(element_id)
    )
    m = re.search(patron, html, re.S)
    assert m, "No se encontro el bloque <script id=%r> en la plantilla" % element_id
    return json.loads(m.group(1).strip())


def _acronimo_de_la_plantilla(mapa: dict, columna: str) -> str:
    """Replica exacta de ``acronimoResultado()`` de la plantilla.

    La funcion real es ``CUENTA_RESULTADO_ACRONIMOS[c] || c``: el acronimo
    del catalogo y, si no existe, el propio texto de la columna.
    """
    return mapa.get(columna) or columna


# ---------------------------------------------------------------------------
# 1. El catalogo (fuente unica de verdad)
# ---------------------------------------------------------------------------
def test_el_catalogo_titula_desestimada_como_desest():
    """``ACRONIMOS["DESESTIMADA"]`` debe ser ``"DESEST"``."""
    from app.core.resultado_pruebas import ACRONIMOS

    assert ACRONIMOS[VALOR_LOV] == ACRONIMO_NUEVO


def test_ningun_valor_del_catalogo_usa_el_acronimo_heredado():
    """El acronimo ``NOOK`` no debe quedar como clave ni como valor."""
    from app.core.resultado_pruebas import ACRONIMOS

    assert ACRONIMO_VIEJO not in ACRONIMOS
    assert ACRONIMO_VIEJO not in set(ACRONIMOS.values())
    # Y el resto de categorias conservan su acronimo (no hay colisiones).
    assert ACRONIMOS["NOK"] == "NOK"
    assert ACRONIMOS["OK"] == "OK"
    assert ACRONIMOS["N/A"] == "N/A"
    assert ACRONIMOS["OK CON OBS."] == "OBS"
    assert ACRONIMOS["POSTERGADA"] == "POST"
    assert ACRONIMOS["(en blanco)"] == "S/D"


def test_la_paleta_de_desestimada_no_cambia():
    """El cambio es de presentacion: ni la clave ni los colores cambian."""
    from app.core.resultado_pruebas import COLORES

    assert COLORES[VALOR_LOV] == COLOR_DESESTIMADA


def test_el_valor_del_lov_no_cambia():
    """La columna del pivote se sigue llamando ``DESESTIMADA``."""
    from app.core.resultado_pruebas import (
        RESULTADOS_LOV,
        RESULTADOS_LOV_FORMULARIO,
        lov_js,
    )

    assert VALOR_LOV in RESULTADOS_LOV
    assert VALOR_LOV in RESULTADOS_LOV_FORMULARIO
    assert ACRONIMO_VIEJO not in RESULTADOS_LOV
    assert lov_js() == list(RESULTADOS_LOV) + ["(en blanco)"]


# ---------------------------------------------------------------------------
# 2. La ficha y el badge (lo que ve el usuario en la tarjeta del Kanban)
# ---------------------------------------------------------------------------
def test_la_ficha_del_resultado_usa_el_acronimo_nuevo():
    """``info_resultado()`` devuelve el valor del LOV y el acronimo nuevo."""
    from app.core.resultado_pruebas import info_resultado

    ficha = info_resultado(VALOR_LOV)
    assert ficha is not None
    assert ficha["valor"] == VALOR_LOV
    assert ficha["acronimo"] == ACRONIMO_NUEVO
    assert ficha["bg"] == COLOR_DESESTIMADA["bg"]
    assert ficha["text"] == COLOR_DESESTIMADA["text"]


def test_el_badge_de_la_tarjeta_muestra_desest_y_conserva_el_color():
    """El badge muestra ``DESEST`` y conserva el violeta y el valor LOV."""
    from app.core.resultado_pruebas import (
        info_resultado,
        render_badge_resultado,
    )

    html = render_badge_resultado(info_resultado(VALOR_LOV))
    assert "DESEST" in html
    assert "NOOK" not in html
    assert 'data-resultado-pruebas="DESESTIMADA"' in html
    assert COLOR_DESESTIMADA["bg"] in html


# ---------------------------------------------------------------------------
# 3. La plantilla del dashboard
# ---------------------------------------------------------------------------
def test_la_plantilla_no_hardcodea_el_acronimo_heredado():
    """Ni en codigo ni en comentarios debe quedar la cadena ``NOOK``."""
    texto = _texto_plantilla()

    assert ACRONIMO_VIEJO not in texto


def test_la_plantilla_toma_el_titulo_del_json_inyectado():
    """El JS debe leer los acronimos del JSON del servidor, no redeclararlos."""
    texto = _texto_plantilla()

    assert "CUENTA_RESULTADO_ACRONIMOS" in texto
    assert "cuenta-resultado-acronimos" in texto
    # El titulo de la columna se calcula con el mapa inyectado...
    assert "acronimoResultado(c)" in texto
    # ...y no con un literal escrito a mano en la plantilla.
    assert '"DESESTIMADA": "NOOK"' not in texto
    assert "'DESESTIMADA': 'NOOK'" not in texto


def test_el_drilldown_conserva_el_valor_del_lov():
    """El drill-down sigue filtrando por ``DESESTIMADA`` (valor del LOV).

    El acronimo es solo de presentacion: el parametro ``resultado`` del
    endpoint de detalle debe seguir llevando el valor del LOV, porque es
    lo que el backend sabe filtrar.
    """
    texto = _texto_plantilla()
    fuente = FUENTE_METRICAS.read_text(encoding="utf-8")

    # El JS construye la URL con la CLAVE de la columna (``c``), no con el
    # acronimo (``acro``).
    assert "'&resultado=' + encodeURIComponent(c)" in texto
    # Y el backend filtra por el valor del LOV.
    assert 'resultado_norm.in_(["DESESTIMADA", "DESESTIMADO"])' in fuente


# ---------------------------------------------------------------------------
# 4. Extremo a extremo: el HTML que sirve el servidor
# ---------------------------------------------------------------------------
def test_el_dashboard_inyecta_el_acronimo_nuevo(local_client, admin_con_sesion):
    """GET /dashboard sirve el JSON con ``DESESTIMADA`` -> ``DESEST``."""
    r = local_client.get("/dashboard")
    assert r.status_code == 200, r.text
    html = r.text

    acronimos = _json_inyectado(html, "cuenta-resultado-acronimos")
    assert acronimos[VALOR_LOV] == ACRONIMO_NUEVO
    assert ACRONIMO_VIEJO not in acronimos
    assert ACRONIMO_VIEJO not in set(acronimos.values())
    # El HTML servido no debe contener el acronimo heredado.
    assert ACRONIMO_VIEJO not in html

    # Y el titulo que el JS va a pintar para esa columna es "DESEST".
    assert _acronimo_de_la_plantilla(acronimos, VALOR_LOV) == ACRONIMO_NUEVO


def test_el_dashboard_sigue_inyectando_la_paleta_y_el_lov(
    local_client, admin_con_sesion
):
    """La paleta y la lista de columnas no se tocan con el renombrado."""
    r = local_client.get("/dashboard")
    assert r.status_code == 200, r.text
    html = r.text

    colores = _json_inyectado(html, "cuenta-resultado-paleta")
    lov = _json_inyectado(html, "cuenta-resultado-lov")

    assert colores[VALOR_LOV] == COLOR_DESESTIMADA
    assert VALOR_LOV in lov
    assert ACRONIMO_VIEJO not in lov
