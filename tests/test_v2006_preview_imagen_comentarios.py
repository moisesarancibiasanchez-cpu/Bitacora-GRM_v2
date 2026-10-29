"""
Regresiones de V2.006: previsualizacion de las imagenes de la pestana de
COMENTARIOS del detalle del ticket, y unificacion de las dos rutas que
renderizan ese modal.

Contexto del defecto
--------------------
El proyecto tiene un lightbox de previsualizacion de imagenes
(``app/static/js/image-preview.js``). Se activa de dos formas:

  1. de forma EXPLICITA, con el atributo ``data-preview-image``;
  2. de forma IMPLICITA, con cualquier ``<img>`` dentro de ``#modal-root``
     cuyo ``src`` termine en extension de imagen (.png/.jpg/...).

La pestana "Adjuntos" del modal usaba la forma explicita y funcionaba. La
pestana "Comentarios", en cambio, renderiza sus adjuntos inline SIN ese
atributo y con un ``src`` que es la URL del endpoint de descarga::

    <img src="/api/v1/adjuntos/{{ a.id }}/descargar" ...>

Esa URL **no termina en extension**, asi que la regla implicita tampoco la
detectaba. Al pulsar la imagen de un comentario no se abria ninguna vista
previa.

Ademas, el modal de detalle se renderiza desde DOS rutas distintas:

  * ``app/api/v1/tickets.py::detalle_html`` (la ruta normal: Kanban, lista de
    tickets, dashboard, timeline, Gantt y calendario) y los otros tres
    endpoints de ``tickets.py`` que re-renderizan el modal;
  * ``app/api/v1/features.py::_render_detalle_modal_response`` (los
    re-renderes tras crear, editar o borrar un comentario).

Cada una montaba sus propias consultas y lo hacian de forma divergente:

  * la ruta de ``tickets.py`` NO precargaba los adjuntos por comentario, asi
    que la miniatura de una imagen adjunta a un comentario **no se
    renderizaba** en la pestana "Comentarios" (solo aparecia de rebote en
    la pestana "Adjuntos" y despues de postear el comentario);
  * la ruta de ``tickets.py`` NO separaba los adjuntos del ticket de los de
    los comentarios, de modo que los adjuntos de un comentario aparecian de
    rebote en la pestana "Adjuntos";
  * la ruta de ``tickets.py`` NO filtraba los comentarios INTERNOS, de modo
    que un SOLICITANTE podia leerlos (los internos son del equipo, nunca
    del solicitante).

Causa raiz: no existia una fuente unica de verdad para los datos del modal.
Este lote la crea (``app/services/ticket_modal_service.py``) y conecta las
dos rutas.

Que fija esta suite
-------------------
  * que la imagen de un comentario se renderice con el atributo que activa
    el lightbox (y con su titulo),
  * que un archivo que NO es imagen no se marque como previsualizable,
  * que una imagen cuyo archivo fisico ya no existe no se pinte como
    imagen rota sino con el aviso de "Archivo no disponible",
  * que los adjuntos de un comentario NO aparezcan en la pestana "Adjuntos",
  * que un solicitante NO vea los comentarios internos,
  * que las dos rutas de render produzcan lo mismo,
  * que el lightbox reconozca la URL del endpoint de adjuntos, de modo que
    la previsualizacion no dependa de un atributo explicito,
  * que la sintaxis JavaScript del lightbox siga siendo valida.

Todos los tests operan sobre la base SQLite temporal de la suite (ver
``tests/conftest.py``): nunca leen ni escriben en la base de datos de
produccion.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
JS_LIGHTBOX = RAIZ / "app" / "static" / "js" / "image-preview.js"
JS_EVENTOS = RAIZ / "app" / "static" / "js" / "htmx-events.js"
PLANTILLA_BASE = RAIZ / "app" / "templates" / "base.html"
PLANTILLA_MODAL = RAIZ / "app" / "templates" / "tickets" / "detalle_modal.py"
SRC_TICKETS = RAIZ / "app" / "api" / "v1" / "tickets.py"
SRC_FEATURES = RAIZ / "app" / "api" / "v1" / "features.py"

CLAVE = "Clave-local-de-regresion-2026"

#: PNG minimo valido (1x1 transparente). Sirve como contenido de respaldo.
PNG_MINIMO = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
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


def _usuario(db_session, username, rol):
    from app.core.security import hash_password
    from app.models.usuario import Usuario

    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        usuario = Usuario(
            username=username,
            email="%s@example.test" % username,
            nombre_completo=username,
            hashed_password=hash_password(CLAVE),
            rol=rol,
            is_active=True,
        )
        db_session.add(usuario)
        db_session.commit()
        db_session.refresh(usuario)
    return usuario


@pytest.fixture
def admin_con_sesion(local_client, db_session):
    """Administrador autenticado en el cliente HTTP local."""
    from app.models.usuario import RolUsuario

    usuario = _usuario(db_session, "v2006_admin_preview", RolUsuario.ADMINISTRADOR)
    login = local_client.post(
        "/api/v1/auth/login",
        json={"username": usuario.username, "password": CLAVE},
    )
    assert login.status_code == 200, login.text
    return usuario


@pytest.fixture
def solicitante_con_sesion(local_client, db_session):
    """Solicitante autenticado en el cliente HTTP local."""
    from app.models.usuario import RolUsuario

    usuario = _usuario(db_session, "v2006_solicitante", RolUsuario.SOLICITANTE)
    login = local_client.post(
        "/api/v1/auth/login",
        json={"username": usuario.username, "password": CLAVE},
    )
    assert login.status_code == 200, login.text
    return usuario


def _crear_ticket_con_comentario(db_session, usuario, codigo, texto="Comentario con imagen adjunta",
                                 es_interno=False):
    """Crea ticket + estado + comentario y devuelve (ticket, comentario)."""
    from app.models.comentario import Comentario
    from app.models.estado import Estado
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia

    estado = db_session.query(Estado).filter(Estado.nombre == "En desarrollo").first()
    if estado is None:
        estado = Estado(nombre="En desarrollo", color="#3b82f6", orden=1)
        db_session.add(estado)
        db_session.commit()
        db_session.refresh(estado)

    ticket = Ticket(
        codigo=codigo,
        titulo="Ticket de regresion V2.006",
        descripcion="Creado por la suite de regresion de V2.006.",
        tipo=TipoIncidencia.INCIDENCIA,
        prioridad=Prioridad.MEDIA,
        estado_id=estado.id,
        creador_id=usuario.id,
        asignado_id=usuario.id,
        archivado=False,
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    comentario = Comentario(
        ticket_id=ticket.id,
        usuario_id=usuario.id,
        texto=texto,
        es_interno=es_interno,
        editado=False,
    )
    db_session.add(comentario)
    db_session.commit()
    db_session.refresh(comentario)
    return ticket, comentario


def _crear_adjunto(db_session, usuario, ticket, comentario, nombre, mime_type,
                   contenido=PNG_MINIMO, ruta_falsa=False):
    """Crea un adjunto (con o sin copia fisica) y devuelve su id."""
    from app.models.adjunto import Adjunto

    adjunto = Adjunto(
        ticket_id=ticket.id,
        comentario_id=comentario.id,
        usuario_id=usuario.id,
        nombre_original=nombre,
        nombre_storage="v2006_%d_%s" % (comentario.id, nombre),
        ruta=("ruta/inexistente/%s" % nombre) if ruta_falsa else ("v2006/%s" % nombre),
        mime_type=mime_type,
        tamano_bytes=len(contenido) if contenido else 0,
        contenido=contenido,
    )
    db_session.add(adjunto)
    db_session.commit()
    db_session.refresh(adjunto)
    return adjunto.id


def _html_modal(local_client, ticket_id, tab="comentarios"):
    """Devuelve el HTML del modal de detalle en la pestana indicada."""
    r = local_client.get("/api/v1/tickets/%d/detalle-html" % ticket_id,
                         params={"tab": tab})
    assert r.status_code == 200, r.text
    return r.text


def _regex_del_js(nombre_variable):
    """Extrae del JS del lightbox una expresion regular literal.

    Devuelve el objeto ``re`` de Python equivalente (los delimitadores ``/``
    de JavaScript y los escapes ``\\/`` se traducen).
    """
    fuente = JS_LIGHTBOX.read_text(encoding="utf-8")
    m = re.search(
        r"var\s+%s\s*=\s*/(.*?)/([a-z]*)\s*;" % re.escape(nombre_variable),
        fuente, re.S,
    )
    assert m, "no se encontro la expresion %s en image-preview.js" % nombre_variable
    patron = m.group(1).replace("\\/", "/")
    flags = re.IGNORECASE if "i" in m.group(2) else 0
    return re.compile(patron, flags)


def _cargar_validador_js():
    """Carga el validador de sintaxis JS del lote V2.003 (mismo lexico)."""
    ruta = RAIZ / "tests" / "test_v2003_sintaxis_js_plantillas.py"
    spec = importlib.util.spec_from_file_location("validador_v2003", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ---------------------------------------------------------------------------
# 1. El markup de los adjuntos del comentario
# ---------------------------------------------------------------------------
def test_la_imagen_del_comentario_lleva_el_atributo_de_preview(
    local_client, db_session, admin_con_sesion
):
    """La imagen del comentario se marca para el lightbox."""
    ticket, comentario = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-IMG-001")
    adjunto_id = _crear_adjunto(
        db_session, admin_con_sesion, ticket, comentario, "captura.png", "image/png")

    html = _html_modal(local_client, ticket.id)

    assert "data-preview-image" in html
    assert 'data-preview-title="captura.png"' in html
    # La miniatura apunta al endpoint de descarga y esta marcada.
    assert re.search(
        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"[^>]*data-preview-image' % adjunto_id,
        html, re.S,
    ), "la imagen del comentario no lleva el atributo de vista previa"
    # El resto del enlace sigue siendo la descarga del archivo.
    assert 'href="/api/v1/adjuntos/%d/descargar"' % adjunto_id in html


def test_un_archivo_que_no_es_imagen_no_se_marca_como_preview(
    local_client, db_session, admin_con_sesion
):
    """Un PDF no debe abrir el lightbox."""
    ticket, comentario = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-PDF-001")
    adjunto_id = _crear_adjunto(
        db_session, admin_con_sesion, ticket, comentario,
        "evidencia.pdf", "application/pdf", contenido=b"%PDF-1.4\n%%EOF\n")

    html = _html_modal(local_client, ticket.id)

    assert not re.search(
        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"' % adjunto_id, html, re.S
    ), "un archivo que no es imagen se pinto como <img>"
    # El enlace de descarga sigue presente.
    assert 'href="/api/v1/adjuntos/%d/descargar"' % adjunto_id in html


def test_una_imagen_no_disponible_avisa_en_vez_de_romperse(
    local_client, db_session, admin_con_sesion
):
    """Si el archivo fisico no existe, se avisa (igual que en "Adjuntos")."""
    ticket, comentario = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-NODISP-001")
    adjunto_id = _crear_adjunto(
        db_session, admin_con_sesion, ticket, comentario, "purgada.png",
        "image/png", contenido=None, ruta_falsa=True)

    html = _html_modal(local_client, ticket.id)

    assert not re.search(
        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"' % adjunto_id, html, re.S
    ), "se pinto una imagen cuyo archivo no esta disponible"
    assert "Archivo no disponible" in html


def _panel(html, nombre):
    """Devuelve solo el HTML de una pestaña del modal.

    El modal renderiza TODAS las pestañas en el mismo documento (las
    inactivas se ocultan con CSS), asi que para afirmar sobre una pestaña
    hay que recortar su seccion.
    """
    m = re.search(r'data-panel="%s"' % re.escape(nombre), html)
    assert m, "no se encontro la pestaña %r en el modal" % nombre
    ini = m.start()
    m2 = re.search(r'data-panel="', html[ini + 20:])
    fin = ini + 20 + m2.start() if m2 else len(html)
    return html[ini:fin]


def test_los_adjuntos_de_un_comentario_no_aparecen_en_la_pestana_adjuntos(
    local_client, db_session, admin_con_sesion
):
    """La pestana "Adjuntos" es la de los archivos del TICKET."""
    ticket, comentario = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-SEPAR-001")
    adjunto_id = _crear_adjunto(
        db_session, admin_con_sesion, ticket, comentario, "solo-comentario.png",
        "image/png")

    html = _html_modal(local_client, ticket.id, tab="adjuntos")

    # En la pestana "Adjuntos" no debe salir el archivo del comentario...
    assert not re.search(
        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"' % adjunto_id,
        _panel(html, "adjuntos"), re.S
    ), "un adjunto de comentario aparecio en la pestana de adjuntos del ticket"
    # ...pero si debe verse inline dentro del comentario.
    assert re.search(
        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"[^>]*data-preview-image' % adjunto_id,
        _panel(html, "comentarios"), re.S
    ), "el adjunto del comentario no se pinto dentro del comentario"


# ---------------------------------------------------------------------------
# 2. Seguridad: los comentarios internos no se muestran a los solicitantes
# ---------------------------------------------------------------------------
def test_un_solicitante_no_ve_los_comentarios_internos(
    local_client, db_session, admin_con_sesion, solicitante_con_sesion
):
    """Los comentarios INTERNOS son del equipo, no del solicitante."""
    ticket, _com_publico = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-INT-001",
        texto="Comentario visible para todos", es_interno=False)
    from app.models.comentario import Comentario

    interno = Comentario(
        ticket_id=ticket.id,
        usuario_id=admin_con_sesion.id,
        texto="NOTA INTERNA que el solicitante no debe leer",
        es_interno=True,
        editado=False,
    )
    db_session.add(interno)
    db_session.commit()

    html = _html_modal(local_client, ticket.id)

    assert "Comentario visible para todos" in html
    assert "NOTA INTERNA que el solicitante no debe leer" not in html, (
        "un solicitante pudo leer un comentario interno")


def test_un_agente_si_ve_los_comentarios_internos(
    local_client, db_session, admin_con_sesion
):
    """El equipo (administrador) si ve los comentarios internos."""
    ticket, _com = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-INT-002",
        texto="NOTA INTERNA del equipo", es_interno=True)

    html = _html_modal(local_client, ticket.id)

    assert "NOTA INTERNA del equipo" in html


# ---------------------------------------------------------------------------
# 3. Las dos rutas de render deben coincidir
# ---------------------------------------------------------------------------
def test_las_dos_rutas_de_render_muestran_lo_mismo(
    local_client, db_session, admin_con_sesion
):
    """La ruta de features.py y la de tickets.py pintan lo mismo."""
    from app.api.v1.features import _render_detalle_modal_response

    ticket, comentario = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-DOSRUTAS-001")
    adjunto_id = _crear_adjunto(
        db_session, admin_con_sesion, ticket, comentario, "captura.png", "image/png")

    html_tickets = _html_modal(local_client, ticket.id)

    db_session.refresh(ticket)
    respuesta = _render_detalle_modal_response(
        db_session, ticket, admin_con_sesion, active_tab="comentarios")
    html_features = (
        respuesta.body.decode("utf-8") if hasattr(respuesta, "body") else str(respuesta)
    )

    for html, nombre in ((html_tickets, "tickets.py"), (html_features, "features.py")):
        assert re.search(
            r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"[^>]*data-preview-image' % adjunto_id,
            html, re.S,
        ), "la ruta %s no pinto la imagen del comentario con vista previa" % nombre


def test_el_ssot_del_modal_es_la_unica_fuente():
    """Las dos rutas de render consumen el helper compartido.

    Si alguien reintroduce consultas propias de comentarios/adjuntos, este
    test avisa: el modal volveria a depender de por donde se abre.
    """
    tickets = SRC_TICKETS.read_text(encoding="utf-8")
    features = SRC_FEATURES.read_text(encoding="utf-8")

    for nombre, fuente in (("tickets.py", tickets), ("features.py", features)):
        assert "ticket_modal_service.comentarios_visibles" in fuente, (
            "%s no usa el SSOT de comentarios" % nombre)
        assert "ticket_modal_service.adjuntos_del_ticket" in fuente, (
            "%s no usa el SSOT de adjuntos del ticket" % nombre)
        assert "ticket_modal_service.adjuntos_por_comentario" in fuente, (
            "%s no precarga los adjuntos por comentario" % nombre)
        # Dentro del render del modal no debe quedar ninguna consulta propia
        # de comentarios (fuera de ese render si puede haber consultas
        # legitimas, por ejemplo al editar un comentario).
        cuerpo = _cuerpo_render(features, "_render_detalle_modal_response") \
            if nombre == "features.py" else ""
        if cuerpo:
            assert "db.query(Comentario)" not in cuerpo, (
                "%s vuelve a consultar los comentarios por su cuenta" % nombre)


def _cuerpo_render(fuente, nombre_funcion):
    """Devuelve el codigo de una funcion de primer nivel del fichero."""
    i = fuente.find("def %s(" % nombre_funcion)
    if i < 0:
        return ""
    j = fuente.find("\ndef ", i + 1)
    return fuente[i:j] if j > 0 else fuente[i:]


# ---------------------------------------------------------------------------
# 4. El lightbox
# ---------------------------------------------------------------------------
def test_el_lightbox_reconoce_la_url_de_descarga_de_adjuntos():
    """La URL del endpoint de adjuntos se tiene que reconocer como imagen."""
    regex = _regex_del_js("ADJUNTOS_URL")

    assert regex.search("/api/v1/adjuntos/12/descargar")
    assert regex.search("/api/v1/adjuntos/12/descargar?filename=captura.png")
    # Y no debe capturar otras URLs.
    assert not regex.search("/api/v1/tickets/12/detalle-html")
    assert not regex.search("/api/v1/adjuntos/12/eliminar")


def test_la_deteccion_por_extension_sigue_funcionando():
    """No se rompe la regla por extension que ya usaba el proyecto."""
    regex = _regex_del_js("IMG_EXT")

    for url in ("/static/img/logo.png", "/x/foto.JPG", "/x/gif.gif?v=2",
                "/x/vector.svg", "/x/animacion.webp"):
        assert regex.search(url), "deberia detectar la imagen %s" % url
    assert not regex.search("/api/v1/adjuntos/12/descargar")
    assert not regex.search("/x/documento.pdf")


def test_el_lightbox_no_engancha_dos_veces_la_misma_imagen():
    """La imagen dentro de un ENLACE con data-preview-image se cubre una vez."""
    fuente = JS_LIGHTBOX.read_text(encoding="utf-8")

    assert "closest('[data-preview-image]')" in fuente
    assert "contenedor.tagName === 'A'" in fuente


def test_reinit_modal_extras_reengancha_el_lightbox():
    """Las vias que insertan el modal con innerHTML deben re-engancharlo.

    Sin esta llamada, en Kanban, Gantt, calendario, command palette y
    dashboard el modal se inserta con fetch + innerHTML, htmx no emite
    htmx:afterSwap y la vista previa se queda sin enganchar.
    """
    fuente = JS_EVENTOS.read_text(encoding="utf-8")

    assert "BitacoraImagePreview" in fuente
    assert "BitacoraImagePreview.attach" in fuente


def test_la_plantilla_base_carga_el_lightbox():
    """El script del lightbox tiene que seguir cargado en todas las paginas."""
    html = PLANTILLA_BASE.read_text(encoding="utf-8")

    assert "/static/js/image-preview.js" in html


def test_la_sintaxis_js_del_lightbox_es_valida():
    """El fichero JS del lightbox no puede tener errores de sintaxis.

    Se reutiliza el lexico del lote V2.003 (mismo validador, sin dependencias).
    """
    validador = _cargar_validador_js()
    codigo = JS_LIGHTBOX.read_text(encoding="utf-8")

    problemas = validador.valida_js("image-preview.js", codigo)

    assert not problemas, "errores de sintaxis JS: %s" % problemas


def test_la_sintaxis_js_de_htmx_events_es_valida():
    """El fichero que engancha el lightbox tampoco puede tener errores JS."""
    validador = _cargar_validador_js()
    codigo = JS_EVENTOS.read_text(encoding="utf-8")

    problemas = validador.valida_js("htmx-events.js", codigo)

    assert not problemas, "errores de sintaxis JS: %s" % problemas


# ---------------------------------------------------------------------------
# 5. No se rompe lo que ya funcionaba
# ---------------------------------------------------------------------------
def test_los_adjuntos_del_ticket_siguen_con_preview():
    """La pestana "Adjuntos" del ticket conserva su vista previa."""
    fuente = PLANTILLA_MODAL.read_text(encoding="utf-8")

    # El bloque de la pestana "Adjuntos" sigue marcando la imagen.
    assert fuente.count("data-preview-image") >= 2, (
        "se perdio el atributo de vista previa en la pestana de adjuntos")


def test_el_modal_sigue_ofreciendo_la_pestana_de_comentarios():
    """La pestana existe y sigue mostrando el numero de comentarios."""
    fuente = PLANTILLA_MODAL.read_text(encoding="utf-8")

    assert 'data-tab="comentarios"' in fuente
    assert 'data-panel="comentarios"' in fuente


# ---------------------------------------------------------------------------
# 6. Regresion del 500 en el listado JSON de comentarios
# ---------------------------------------------------------------------------
def test_el_listado_de_comentarios_no_falla_con_texto_largo(
    local_client, db_session, admin_con_sesion
):
    """Un comentario legacy mas largo de 5.000 caracteres no debe dar 500.

    En produccion, GET /api/v1/tickets/6/comentarios devolvia HTTP 500 de
    forma determinista: el comentario id=10 del ticket 6 tiene 17.607
    caracteres y el esquema de RESPUESTA (ComentarioRead) heredia el
    ``max_length=5000`` del esquema de escritura, de modo que Pydantic
    fallaba al serializar la respuesta (ResponseValidationError -> 500).
    El limite de 5.000 sigue vigente al escribir; solo se relaja al LEER.
    """
    from app.models.comentario import Comentario

    ticket, _com = _crear_ticket_con_comentario(
        db_session, admin_con_sesion, "V2006-TEXTO-LARGO-001")
    largo = Comentario(
        ticket_id=ticket.id,
        usuario_id=admin_con_sesion.id,
        texto="X" * 17607,
        es_interno=False,
        editado=False,
    )
    db_session.add(largo)
    db_session.commit()

    r = local_client.get("/api/v1/tickets/%d/comentarios" % ticket.id)

    assert r.status_code == 200, (
        "el listado de comentarios devolvio %s: %s" % (r.status_code, r.text[:300]))
    cuerpo = r.json()
    textos = [c.get("texto", "") for c in cuerpo]
    assert any(len(t) == 17607 for t in textos), (
        "el comentario largo no se devolvio completo")


def test_al_crear_un_comentario_se_mantiene_el_limite_de_5000(local_client):
    """La validacion de ESCRITURA no se relaja: 5.000 caracteres es el tope."""
    r = local_client.post(
        "/api/v1/tickets/1/comentarios",
        json={"texto": "X" * 5001},
    )
    assert r.status_code in (400, 404, 422), (
        "la escritura acepto un comentario de mas de 5.000 caracteres: %s"
        % r.status_code)


# ---------------------------------------------------------------------------
# 7. Regresion del KPI "Incidencias Abiertas" (comparacion con acentos)
# ---------------------------------------------------------------------------
def test_el_kpi_de_incidencias_abiertas_excluye_produccion_ok_con_tilde(
    local_client, db_session, admin_con_sesion
):
    """El KPI no puede contar como "abiertas" las incidencias ya desplegadas.

    El nombre canonico del estado es 'Produccion OK' (con tilde): lo insertan
    asi la siembra (app/db/init_db.py) y la migracion 4.6. Comparar con
    ``lower(nombre) NOT IN ('produccion ok')`` NO lo excluia nunca, porque
    ``lower()`` no quita acentos: en una base nueva el KPI contaba como
    abiertas las 702 incidencias ya desplegadas.
    """
    from app.models.estado import Estado
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia

    # Nombre CANONICO del estado, con tilde ('Produccion OK' con 'o' acentuada).
    # Se escribe con escape unicode para que este fichero siga siendo ASCII,
    # pero el valor es exactamente el que insertan la siembra y la
    # migracion 4.6.
    NOMBRE_PRODUCCION_OK = "Producci\u00f3n OK"

    estado_produccion = db_session.query(Estado).filter(
        Estado.nombre == NOMBRE_PRODUCCION_OK).first()
    if estado_produccion is None:
        estado_produccion = Estado(
            nombre=NOMBRE_PRODUCCION_OK, color="#0d9488", orden=99,
            es_inicial=False, es_final=True, categoria="produccion_ok",
        )
        db_session.add(estado_produccion)
        db_session.commit()
        db_session.refresh(estado_produccion)

    estado_abierto = db_session.query(Estado).filter(
        Estado.nombre == "BackLog").first()
    if estado_abierto is None:
        estado_abierto = Estado(
            nombre="BackLog", color="#f59e0b", orden=98,
            es_inicial=True, es_final=False, categoria="abierto",
        )
        db_session.add(estado_abierto)
        db_session.commit()
        db_session.refresh(estado_abierto)

    def _incidencia(codigo, estado_id, resultado=None):
        t = Ticket(
            codigo=codigo,
            titulo="KPI V2.006",
            descripcion="d",
            tipo=TipoIncidencia.INCIDENCIA,
            prioridad=Prioridad.MEDIA,
            estado_id=estado_id,
            creador_id=admin_con_sesion.id,
            asignado_id=admin_con_sesion.id,
            archivado=False,
            resultado_pruebas=resultado,
        )
        db_session.add(t)
        db_session.commit()
        return t

    def _backlog():
        r = local_client.get("/api/v1/metricas/dashboard-completo")
        assert r.status_code == 200, r.text
        return r.json()["incidencias"]["backlog_7d"]

    # Se mide el DELTA: la base de la suite la comparten otros tests de este
    # modulo, asi que el valor absoluto no es estable.
    antes = _backlog()

    _incidencia("V2006-KPI-PROD", estado_produccion.id)
    _incidencia("V2006-KPI-ABIERTA", estado_abierto.id)
    _incidencia("V2006-KPI-DESEST", estado_abierto.id, resultado="DESESTIMADA")

    despues = _backlog()

    # El ticket en 'Produccion OK' NO cuenta, y el DESESTIMADA tampoco:
    # de los tres tickets creados, solo uno sigue siendo una incidencia
    # abierta.
    assert despues == antes + 1, (
        "el KPI cambio de %s a %s (se esperaba +1)" % (antes, despues))
