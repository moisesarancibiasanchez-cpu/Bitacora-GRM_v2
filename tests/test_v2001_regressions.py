"""Regresiones deterministas de los cambios de V2.001.

Cada test cubre un comportamiento OBSERVABLE del cambio, no su
implementación interna. Todos operan sobre la base SQLite temporal de la
suite (ver ``tests/conftest.py``) o sobre bases aisladas en memoria: nunca
leen ni escriben en la base de datos de producción.

Cambios cubiertos:

  1. El modal de cambio de contraseña exige sesión (401 sin cookie).
  2. La siembra de estados crea el flujo estándar COMPLETO aunque ya
     exista 'Producción OK' (bug del ``KeyError: 'Nuevo'`` en base nueva).
  3. La siembra de transiciones no revienta si falta algún estado.
  4. El dashboard escapa los datos del ticket antes de inyectarlos en el DOM.
  5. El panel de deadlines no inyecta el JSON del resultado con ``innerHTML``.
  6. La guía de onboarding define las anclas que enlaza.
  7. El barrido anónimo está disponible y documentado.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent


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
def cliente_anonimo(app_and_schema):
    """Cliente HTTP local SIN cookie ni token (visitante anonimo)."""
    app, _engine = app_and_schema
    with TestClient(app) as client:
        client.cookies.clear()
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


def _crear_usuario(db_session, username, rol, password="Clave-local-de-regresion-2026"):
    """Crea un usuario persistente y lo devuelve."""
    from app.core.security import hash_password
    from app.models.usuario import Usuario

    usuario = Usuario(
        username=username,
        email=f"{username}@example.test",
        nombre_completo=f"Usuario {username}",
        hashed_password=hash_password(password),
        rol=rol,
        is_active=True,
    )
    db_session.add(usuario)
    db_session.commit()
    db_session.refresh(usuario)
    return usuario


@pytest.fixture
def sesion_aislada():
    """Sesion SQLAlchemy sobre una SQLite EN MEMORIA con su propio motor.

    Se usa para las pruebas de siembra: no deben tocar la base de la suite
    (ni la de desarrollo) porque crean y borran estados.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base

    motor = create_engine("sqlite://", future=True)
    Base.metadata.create_all(motor)
    sesion = sessionmaker(bind=motor, future=True)()
    try:
        yield sesion
    finally:
        sesion.close()
        motor.dispose()


# ---------------------------------------------------------------------------
# 1. El modal de cambio de contraseña exige sesión
# ---------------------------------------------------------------------------
def test_el_modal_de_cambio_de_contrasena_exige_sesion(cliente_anonimo):
    """Sin cookie ni token, el modal NO se sirve: responde 401.

    Antes devolvia 200 a cualquier visitante anonimo. El fragmento no
    filtra datos, pero es una superficie publica innecesaria.
    """
    respuesta = cliente_anonimo.get("/api/v1/auth/cambiar-password-modal")

    assert respuesta.status_code == 401, respuesta.text


def test_el_modal_de_cambio_de_contrasena_se_sirve_con_sesion(local_client, db_session):
    """Con sesion de administrador, el modal se sirve con su plantilla."""
    from app.models.usuario import RolUsuario

    _crear_usuario(db_session, "v2001_admin_modal", RolUsuario.ADMINISTRADOR)

    login = local_client.post(
        "/api/v1/auth/login",
        json={"username": "v2001_admin_modal", "password": "Clave-local-de-regresion-2026"},
    )
    assert login.status_code == 200, login.text

    respuesta = local_client.get("/api/v1/auth/cambiar-password-modal")

    assert respuesta.status_code == 200, respuesta.text
    assert "cambiar" in respuesta.text.lower()


# ---------------------------------------------------------------------------
# 2. La siembra crea el flujo estándar completo aunque falten estados
# ---------------------------------------------------------------------------
def test_la_siembra_crea_el_flujo_estandar_que_falta(sesion_aislada):
    """Si solo existe 'Producción OK', la siembra crea el resto del flujo.

    Este es el estado en el que quedan las bases NUEVAS: la migración 4.6
    inserta 'Producción OK' antes de la siembra y el seed antiguo se salia
    entero, dejando la base sin flujo y con un ``KeyError: 'Nuevo'``.
    """
    from app.db.init_db import seed_estados
    from app.models.estado import Estado

    sesion_aislada.add(Estado(
        nombre="Producción OK", color="#0d9488", orden=7,
        es_inicial=False, es_final=True, categoria="produccion_ok",
        sla_horas=None, descripcion="Creado por la migracion 4.6",
    ))
    sesion_aislada.commit()

    seed_estados(sesion_aislada)
    sesion_aislada.commit()

    nombres = {e.nombre for e in sesion_aislada.query(Estado).all()}
    requeridos = {
        "Nuevo", "En curso", "En espera", "Resuelto", "Cerrado", "Cancelado",
    }
    assert requeridos <= nombres, "faltan estados del flujo: %r" % (
        requeridos - nombres,
    )
    assert "Producción OK" in nombres

    # El estado inicial tiene que existir: sin él no se puede abrir un ticket.
    iniciales = [e.nombre for e in sesion_aislada.query(Estado).all() if e.es_inicial]
    assert iniciales, "no hay ningun estado inicial"


def test_la_siembra_no_duplica_los_estados_que_ya_existen(sesion_aislada):
    """La siembra es idempotente: no crea un segundo 'Producción OK'."""
    from app.db.init_db import seed_estados
    from app.models.estado import Estado

    sesion_aislada.add(Estado(
        nombre="Producción OK", color="#0d9488", orden=7,
        es_inicial=False, es_final=True, categoria="produccion_ok",
        sla_horas=None, descripcion="Creado por la migracion 4.6",
    ))
    sesion_aislada.commit()

    seed_estados(sesion_aislada)
    sesion_aislada.commit()
    seed_estados(sesion_aislada)
    sesion_aislada.commit()

    produccion_ok = sesion_aislada.query(Estado).filter(
        Estado.nombre == "Producción OK"
    ).all()
    assert len(produccion_ok) == 1, "se duplicó 'Producción OK': %d" % len(produccion_ok)


# ---------------------------------------------------------------------------
# 3. La siembra de transiciones no revienta si falta un estado
# ---------------------------------------------------------------------------
def test_la_siembra_de_transiciones_no_revienta_si_falta_un_estado(sesion_aislada):
    """Con estados incompletos, la siembra omite lo que no puede resolver.

    Antes el ``estados[origen]`` reventaba con ``KeyError`` y abortaba
    TODA la siembra (usuarios, catálogos, etiquetas, tableros...).
    """
    from app.db.init_db import seed_transiciones
    from app.models.estado import Estado

    sesion_aislada.add_all([
        Estado(nombre="Nuevo", color="#64748b", orden=1, es_inicial=True,
               es_final=False, categoria="abierto", sla_horas=24),
        Estado(nombre="En curso", color="#3b82f6", orden=2, es_inicial=False,
               es_final=False, categoria="abierto", sla_horas=48),
    ])
    sesion_aislada.commit()

    # No debe lanzar KeyError.
    seed_transiciones(sesion_aislada)
    sesion_aislada.commit()

    from app.models.estado import TransicionEstado

    transiciones = sesion_aislada.query(TransicionEstado).all()
    assert transiciones, "no se creó ninguna transición resoluble"
    # La única transición resoluble con estos dos estados es Nuevo -> En curso.
    assert len(transiciones) == 1


# ---------------------------------------------------------------------------
# 4. El dashboard escapa los datos del ticket
# ---------------------------------------------------------------------------
def test_el_dashboard_escapa_los_datos_del_ticket():
    """El título del ticket se escapa antes de inyectarlo en el DOM.

    El título lo elige el usuario que abre el ticket: sin escape, un
    título con ``<img src=x onerror=...>`` es XSS almacenado.
    """
    plantilla = (RAIZ / "app" / "templates" / "dashboard" / "index.html").read_text(
        encoding="utf-8"
    )

    # Las apariciones SIN escapar de ``t.titulo`` no deben existir.
    sin_escapar = re.findall(r"\+\s*\(t\.titulo[^)]*\)\s*\+", plantilla)
    assert not sin_escapar, "el título se inyecta sin escapar: %r" % sin_escapar

    # Y debe aparecer escapado al menos una vez.
    assert "_escapeHtml(t.titulo" in plantilla

    # Lo mismo con el nombre del agente (lo elige el usuario al registrarse).
    sin_escapar_agente = re.findall(r"\+\s*\(a\.nombre[^)]*\)\s*\+", plantilla)
    assert not sin_escapar_agente, (
        "el nombre del agente se inyecta sin escapar: %r" % sin_escapar_agente
    )


# ---------------------------------------------------------------------------
# 5. El panel de deadlines no inyecta el JSON con innerHTML
# ---------------------------------------------------------------------------
def test_el_panel_de_deadlines_no_inyecta_el_json_con_innerhtml():
    """El resultado del trigger se pinta con ``textContent``, no con HTML.

    El JSON incluye ``errores``, que concatena el correo del destinatario
    (dato controlado por el usuario) y puede contener ``<``, ``>`` o comillas.
    """
    plantilla = (RAIZ / "app" / "templates" / "admin" / "deadline.html").read_text(
        encoding="utf-8"
    )

    assert "JSON.stringify(data.resultados, null, 2) +" not in plantilla, (
        "el JSON del trigger se sigue inyectando con innerHTML"
    )
    assert "pre.textContent = JSON.stringify(payload, null, 2);" in plantilla


# ---------------------------------------------------------------------------
# 6. La guía de onboarding define las anclas que enlaza
# ---------------------------------------------------------------------------
def test_la_guia_define_las_anclas_que_enlaza():
    """Todo enlace interno ``#ancla`` debe tener su ancla definida.

    La guía enlazaba 39 veces a ``#sec-1``..``#sec-24`` sin definir ninguna
    de esas anclas: en Markdown eran enlaces rotos.
    """
    guia = (RAIZ / "docs" / "GUIA_ONBOARDING.md").read_text(encoding="utf-8")

    destinos = set(re.findall(r"\]\(#([^)]+)\)", guia))
    definidos = set(re.findall(r'id="([^"]+)"', guia))
    definidos |= {
        re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
        for h in re.findall(r"^#{1,6}\s+(.+)$", guia, flags=re.MULTILINE)
    }

    rotas = sorted(d for d in destinos if d not in definidos and d.lower() != "top")
    assert not rotas, "anclas internas rotas en la guía: %r" % rotas


# ---------------------------------------------------------------------------
# 7. El barrido anónimo está disponible y documentado
# ---------------------------------------------------------------------------
def test_el_barrido_anonimo_existe_y_esta_documentado():
    """La herramienta que detecta fugas anónimas está en el repo y en el README."""
    herramienta = RAIZ / "tools" / "verificacion" / "barrer_anonimo.py"
    assert herramienta.exists(), "falta tools/verificacion/barrer_anonimo.py"

    readme = (RAIZ / "tools" / "verificacion" / "README.md").read_text(encoding="utf-8")
    assert "barrer_anonimo.py" in readme, (
        "el barrido anónimo no está documentado en tools/verificacion/README.md"
    )


# ---------------------------------------------------------------------------
# 8. La siembra completa no aborta en una base nueva
# ---------------------------------------------------------------------------
def test_los_tickets_demo_se_omiten_si_falta_el_material_de_demostracion(sesion_aislada):
    """Sin usuarios de demo (SEED_DEMO_USERS apagado) no hay KeyError.

    Antes ``usuarios[creador_un]`` reventaba con ``KeyError: 'usuario1'`` y
    abortaba el resto de la semilla: la base nueva se quedaba a medias y
    el servicio no llegaba a levantar.
    """
    from app.db.init_db import seed_tickets_demo
    from app.models.ticket import Ticket

    # Sin estados, usuarios ni etiquetas de demostracion.
    seed_tickets_demo(sesion_aislada)
    sesion_aislada.commit()

    assert sesion_aislada.query(Ticket).count() == 0


def test_el_arranque_completo_sobre_una_base_nueva_no_falla(tmp_path):
    """``init_database()`` completo, como en el arranque de producción.

    Se ejecuta en un subproceso con ``DATABASE_URL`` apuntando a una
    SQLite temporal, porque el motor de la aplicación se crea al importar
    el modulo de configuracion. Los tests de la suite NUNCA ejecutan esta
    ruta (AUTO_INIT_DB esta apagado ahi), asi que sin esta prueba un fallo
    de arranque solo apareceria al desplegar.
    """
    import os
    import subprocess
    import sys

    script = (
        "import os, sys\n"
        "sys.path.insert(0, %r)\n"
        "os.environ['DATABASE_URL'] = 'sqlite:///' + %r\n"
        "os.environ['SECRET_KEY'] = 'x' * 40\n"
        "from app.db.base import Base\n"
        "from app.db.session import engine\n"
        "from app.db.init_db import init_database\n"
        "Base.metadata.create_all(bind=engine)\n"
        "init_database()\n"
        "from app.db.session import SessionLocal\n"
        "from app.models import Estado, TransicionEstado\n"
        "db = SessionLocal()\n"
        "e = db.query(Estado).count()\n"
        "t = db.query(TransicionEstado).count()\n"
        "db.close()\n"
        "print('ESTADOS=%%d TRANSICIONES=%%d' %% (e, t))\n"
    ) % (str(RAIZ), str(tmp_path / "arranque.db").replace("\\", "/"))

    proceso = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        capture_output=True, text=True, timeout=600,
        # V2.009: sin `encoding` la salida UTF-8 del subproceso se decodifica
        # con el locale del sistema (cp1252 en Windows) y el test falla con
        # "argument of type 'NoneType' is not iterable". El subproceso se
        # lanza SIEMPRE con `-X utf8`, asi que se decodifica como UTF-8.
        encoding="utf-8", errors="replace",
        cwd=str(RAIZ),
    )

    assert proceso.returncode == 0, (
        "init_database() fallo en una base nueva:\n%s\n%s"
        % (proceso.stdout[-2000:], proceso.stderr[-2000:])
    )
    salida = proceso.stdout
    assert "ESTADOS=" in salida, salida[-800:]
    m_estados = re.search(r"ESTADOS=(\d+)", salida)
    m_transiciones = re.search(r"TRANSICIONES=(\d+)", salida)
    assert m_estados and m_transiciones, salida[-800:]
    assert int(m_estados.group(1)) >= 7, "faltan estados del flujo: %s" % m_estados.group(1)
    assert int(m_transiciones.group(1)) >= 15, "faltan transiciones: %s" % m_transiciones.group(1)
