"""Regresiones deterministas de los cambios de V1.006.

Cada test cubre un comportamiento OBSERVABLE del cambio, no su
implementación interna. Todos operan sobre la base SQLite temporal de la
suite (ver ``tests/conftest.py``): nunca leen ni escriben en la base de
datos de producción.
"""
from __future__ import annotations

import re
import shutil
import subprocess
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
    """Cliente HTTP local; no abre conexiones de red."""
    app, _engine = app_and_schema
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db_session(app_and_schema):
    """Sesión SQLAlchemy sobre la SQLite temporal de la suite."""
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


def _crear_estado(db_session, nombre, **kwargs):
    """Crea un estado persistente y lo devuelve."""
    from app.models.estado import Estado

    estado = Estado(nombre=nombre, color="#334155", orden=kwargs.pop("orden", 90), **kwargs)
    db_session.add(estado)
    db_session.commit()
    db_session.refresh(estado)
    return estado


# ---------------------------------------------------------------------------
# 1. Migraciones: fail-closed del arranque
# ---------------------------------------------------------------------------
def test_verificar_esquema_devuelve_cero_en_base_sana(app_and_schema):
    """Con el esquema alineado, `verificar_esquema()` devuelve 0 (arranque)."""
    from app.db.migrations import verificar_esquema

    assert verificar_esquema() == 0


def test_verificar_esquema_devuelve_uno_con_deriva(monkeypatch):
    """Si el esquema deriva, `verificar_esquema()` devuelve 1 (arranque aborta).

    Se simula la deriva sustituyendo SOLO el informador de deriva: la lógica
    de decisión (que linesas cuentan como fallo) es lo que se comprueba.
    """
    from app.db import migrations

    monkeypatch.setattr(
        migrations,
        "report_schema_drift",
        lambda eng=None: ["OK (12 columnas)", "faltan columnas: tickets.fecha_x"],
    )

    assert migrations.verificar_esquema() == 1


def test_verificar_esquema_no_confunde_ok_con_fallo(monkeypatch):
    """Las lineas 'OK (N columnas)' NO son deriva: no pueden abortar el arranque."""
    from app.db import migrations

    monkeypatch.setattr(
        migrations,
        "report_schema_drift",
        lambda eng=None: ["OK (12 columnas)", "OK (8 columnas)"],
    )

    assert migrations.verificar_esquema() == 0


def test_los_errores_de_esquema_abortan_el_arranque(monkeypatch):
    """Si no se pudo alinear el esquema (ADD COLUMN/create_all), se aborta."""
    from app.db import migrations

    monkeypatch.setattr(
        migrations,
        "apply_migrations",
        lambda eng=None: {
            "applied": 0, "skipped": 25, "indexes": 21, "errors": 1,
            "schema_errors": 1, "tables_created": 0, "data_migrated": 0,
        },
    )
    monkeypatch.setattr(
        migrations, "report_schema_drift", lambda eng=None: ["tickets: OK (12 columnas)"]
    )

    assert migrations.verificar_esquema() == 1


def test_los_errores_de_datos_no_abortan_el_arranque(monkeypatch):
    """Un fallo en las migraciones de DATOS no deja el esquema inservible.

    El esquema queda alineado, asi que la aplicacion sirve igual: abortar
    el arranque por esto dejaria los tres servicios caidos sin evitar
    ningun 500.
    """
    from app.db import migrations

    monkeypatch.setattr(
        migrations,
        "apply_migrations",
        lambda eng=None: {
            "applied": 0, "skipped": 25, "indexes": 21, "errors": 3,
            "schema_errors": 0, "tables_created": 0, "data_migrated": 0,
        },
    )
    monkeypatch.setattr(
        migrations, "report_schema_drift", lambda eng=None: ["tickets: OK (12 columnas)"]
    )

    assert migrations.verificar_esquema() == 0


def test_un_error_en_el_guardi_no_tumba_el_servicio(monkeypatch):
    """Si la propia comprobacion falla, se registra y se continua sirviendo."""
    from app.db import migrations

    def falla(*args, **kwargs):
        raise RuntimeError("fallo simulado del guard de esquema")

    monkeypatch.setattr(migrations, "apply_migrations", falla)

    assert migrations.verificar_esquema() == 0


def test_importar_modelos_puebla_el_metadata():
    """`_asegurar_modelos_importados()` registra las tablas en Base.metadata.

    Sin esto, `apply_migrations()` ejecutado fuera de la web trabajaría con
    un metadata VACIO y todas las migraciones fallarian con 'no such table'.
    """
    from app.db.base import Base
    from app.db.migrations import _asegurar_modelos_importados

    _asegurar_modelos_importados()

    assert "tickets" in Base.metadata.tables
    assert "estados" in Base.metadata.tables
    assert len(Base.metadata.tables) > 10


def test_una_base_nueva_queda_con_el_estado_produccion_ok():
    """Sobre una base VACIA las migraciones crean el estado 'Producción OK'.

    El INSERT crudo omitia ``es_entrega``, que es NOT NULL con default de
    SQLAlchemy (lado Python, no del servidor): en una base nueva la
    insercion fallaba con "NOT NULL constraint failed: estados.es_entrega"
    y el estado terminal NO se creaba.
    """
    import tempfile

    from sqlalchemy import create_engine, text

    from app.db.migrations import apply_migrations

    ruta = Path(tempfile.gettempdir()) / "v1006_base_nueva.sqlite"
    for sufijo in ("", "-wal", "-shm"):
        auxiliar = Path(str(ruta) + sufijo)
        if auxiliar.exists():
            auxiliar.unlink()

    motor = create_engine("sqlite:///" + ruta.as_posix())
    try:
        apply_migrations(motor)
        with motor.connect() as conexion:
            filas = conexion.execute(
                text("SELECT nombre, es_entrega FROM estados")
            ).fetchall()
            etapas = conexion.execute(
                text("SELECT COUNT(*) FROM etapas_proyecto")
            ).scalar()
    finally:
        motor.dispose()
        for sufijo in ("", "-wal", "-shm"):
            auxiliar = Path(str(ruta) + sufijo)
            if auxiliar.exists():
                auxiliar.unlink()

    nombres = [f[0] for f in filas]
    assert "Producción OK" in nombres, nombres
    assert etapas == 10


def test_start_sh_aborta_si_el_esquema_no_esta_alineado():
    """`start.sh` invoca `verificar_esquema()` y sale con 1 si falla."""
    texto = (RAIZ / "start.sh").read_text(encoding="utf-8")

    assert "verificar_esquema" in texto
    assert "exit 1" in texto
    # El arranque NO debe continuar "para no dejar el servicio sin respuesta".
    assert "El proceso continúa para no dejar el servicio sin respuesta" not in texto


def test_railway_toml_es_valido_y_sin_claves_duplicadas():
    """`railway.toml` se puede parsear y no repite claves."""
    import tomllib

    with (RAIZ / "railway.toml").open("rb") as fh:
        datos = tomllib.load(fh)

    assert "services" in datos or "deploy" in datos


def test_start_sh_pasa_la_sintaxis_de_bash():
    """`start.sh` es sintácticamente válido para bash."""
    bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
    if not Path(bash).exists():
        pytest.skip("bash no disponible en esta maquina")

    resultado = subprocess.run(
        [bash, "-n", str(RAIZ / "start.sh")],
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr


# ---------------------------------------------------------------------------
# 2. Creación de tickets: `estado_id` con guard de rol
# ---------------------------------------------------------------------------
def test_crear_ticket_respeta_el_estado_solicitado_para_administrador(db_session):
    """Un administrador puede abrir el ticket en el estado que pide."""
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    estado_inicial = _crear_estado(db_session, "V1006 inicial", es_inicial=True, orden=91)
    estado_destino = _crear_estado(db_session, "V1006 destino", orden=92)
    admin = _crear_usuario(db_session, "v1006_admin", RolUsuario.ADMINISTRADOR)

    ticket = TicketService(db_session).crear_ticket(
        {
            "titulo": "Ticket en estado elegido",
            "descripcion": "Descripcion",
            "estado_id": estado_destino.id,
        },
        usuario=admin,
    )
    db_session.commit()

    assert ticket.estado_id == estado_destino.id
    assert ticket.estado_id != estado_inicial.id


def test_crear_ticket_ignora_el_estado_solicitado_para_solicitante(db_session):
    """Un solicitante NO puede saltarse el flujo: va al estado inicial."""
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    _crear_estado(db_session, "V1006 inicial rol", es_inicial=True, orden=93)
    estado_destino = _crear_estado(db_session, "V1006 final rol", es_final=True, orden=94)
    solicitante = _crear_usuario(db_session, "v1006_solicitante", RolUsuario.SOLICITANTE)

    ticket = TicketService(db_session).crear_ticket(
        {
            "titulo": "Ticket de solicitante",
            "descripcion": "Descripcion",
            "estado_id": estado_destino.id,
        },
        usuario=solicitante,
    )
    db_session.commit()

    # No se aplico el estado pedido y el ticket queda en un estado inicial.
    assert ticket.estado_id != estado_destino.id
    assert ticket.estado.es_inicial is True


def test_crear_ticket_rechaza_un_estado_inexistente(db_session):
    """Un estado que no existe se rechaza con error explicito."""
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService, TransicionInvalidaError

    admin = _crear_usuario(db_session, "v1006_admin_estado", RolUsuario.ADMINISTRADOR)

    with pytest.raises(TransicionInvalidaError):
        TicketService(db_session).crear_ticket(
            {
                "titulo": "Ticket con estado inexistente",
                "descripcion": "Descripcion",
                "estado_id": 987654,
            },
            usuario=admin,
        )


def test_crear_ticket_rechaza_titulo_vacio(db_session):
    """Un ticket sin titulo no se crea: la validacion es del lado del servicio."""
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    admin = _crear_usuario(db_session, "v1006_admin_titulo", RolUsuario.ADMINISTRADOR)

    with pytest.raises(ValueError):
        TicketService(db_session).crear_ticket(
            {"titulo": "   ", "descripcion": "Descripcion"},
            usuario=admin,
        )


# ---------------------------------------------------------------------------
# 3. SLA y fechas de cierre
# ---------------------------------------------------------------------------
def test_reordenar_en_la_misma_columna_no_reinicia_el_sla(db_session):
    """Mover una tarjeta dentro de su columna NO reinicia el vencimiento."""
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    _crear_estado(db_session, "V1006 sla origen", es_inicial=True, orden=95, sla_horas=24)
    estado_destino = _crear_estado(db_session, "V1006 sla destino", orden=96, sla_horas=48)
    agente = _crear_usuario(db_session, "v1006_agente_sla", RolUsuario.AGENTE)

    servicio = TicketService(db_session)
    ticket = servicio.crear_ticket(
        {"titulo": "Ticket SLA", "descripcion": "Descripcion"}, usuario=agente
    )
    db_session.commit()

    servicio.cambiar_estado(ticket.id, estado_destino.id, usuario=agente)
    db_session.commit()
    vencimiento_inicial = ticket.fecha_vencimiento_sla
    assert vencimiento_inicial is not None

    servicio.cambiar_estado(
        ticket.id, estado_destino.id, usuario=agente, orden=5
    )
    db_session.commit()

    assert ticket.fecha_vencimiento_sla == vencimiento_inicial


def test_estado_final_registra_fecha_de_completado(db_session):
    """Al mover a un estado final se registra `fecha_completado`."""
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    _crear_estado(db_session, "V1006 final origen", es_inicial=True, orden=97)
    estado_final = _crear_estado(
        db_session, "V1006 final destino", orden=98, es_final=True, sla_horas=None
    )
    agente = _crear_usuario(db_session, "v1006_agente_final", RolUsuario.AGENTE)

    servicio = TicketService(db_session)
    ticket = servicio.crear_ticket(
        {"titulo": "Ticket cierre", "descripcion": "Descripcion"}, usuario=agente
    )
    db_session.commit()

    servicio.cambiar_estado(ticket.id, estado_final.id, usuario=agente)
    db_session.commit()

    assert ticket.fecha_completado is not None


# ---------------------------------------------------------------------------
# 4. Notificacion al responsable: SAVEPOINT (no descarta la transaccion)
# ---------------------------------------------------------------------------
def test_la_notificacion_al_responsable_no_descarta_el_cambio_del_caller(
    db_session, monkeypatch
):
    """Si la notificacion falla, el cambio pendiente del caller sobrevive.

    Con un `db.rollback()` a secas se perdian el cambio de estado, el
    historial y la auditoria, mientras la API respondia 200.
    """
    from app.models.estado import Estado
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario
    from app.services.notificacion_responsable_service import (
        notificar_responsable_columna,
    )

    actor = _crear_usuario(db_session, "v1006_actor", RolUsuario.AGENTE)
    responsable = _crear_usuario(db_session, "v1006_responsable", RolUsuario.AGENTE_SENIOR)

    estado = Estado(
        nombre="V1006 con responsable",
        color="#334155",
        orden=99,
        responsable_id=responsable.id,
    )
    db_session.add(estado)
    db_session.commit()
    db_session.refresh(estado)

    ticket = Ticket(
        codigo="V1006-NOTIF-001",
        titulo="Ticket con notificacion",
        descripcion="Descripcion",
        creador_id=actor.id,
        estado_id=estado.id,
        datos_catalogo={},
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    # Cambio pendiente del llamador, YA materializado en la transaccion.
    ticket.titulo = "Titulo cambiado por el llamador"
    db_session.flush()

    def flush_fallido(*args, **kwargs):
        raise RuntimeError("fallo simulado al insertar la notificacion")

    monkeypatch.setattr(db_session, "flush", flush_fallido)

    resultado = notificar_responsable_columna(
        db_session,
        ticket=ticket,
        estado_destino=estado,
        estado_origen_nombre="V1006 origen",
        actor=actor,
    )

    monkeypatch.undo()

    assert resultado["notif_created"] is False
    db_session.expire_all()
    assert db_session.get(Ticket, ticket.id).titulo == "Titulo cambiado por el llamador"


# ---------------------------------------------------------------------------
# 5. Salud de Celery: latido, ping y control de acceso
# ---------------------------------------------------------------------------
def test_salud_celery_requiere_sesion(local_client):
    """Sin cookie de sesion, `/salud-celery` responde 401."""
    respuesta = local_client.get("/salud-celery")

    assert respuesta.status_code == 401


def test_salud_celery_exige_administrador(local_client, db_session):
    """Con un rol que no es administrador, `/salud-celery` responde 403."""
    from app.models.usuario import RolUsuario

    _crear_usuario(db_session, "v1006_agente_salud", RolUsuario.AGENTE)

    login = local_client.post(
        "/api/v1/auth/login",
        json={"username": "v1006_agente_salud", "password": "Clave-local-de-regresion-2026"},
    )
    assert login.status_code == 200, login.text

    respuesta = local_client.get("/salud-celery")

    assert respuesta.status_code == 403


def test_salud_celery_responde_a_administrador(local_client, db_session):
    """Con sesion de administrador responde 200 y describe worker y beat."""
    from app.models.usuario import RolUsuario

    _crear_usuario(db_session, "v1006_admin_salud", RolUsuario.ADMINISTRADOR)

    login = local_client.post(
        "/api/v1/auth/login",
        json={"username": "v1006_admin_salud", "password": "Clave-local-de-regresion-2026"},
    )
    assert login.status_code == 200, login.text

    respuesta = local_client.get("/salud-celery")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert "worker" in cuerpo
    assert "beat" in cuerpo
    assert "colas" in cuerpo
    assert "tareas_programadas" in cuerpo
    assert any(
        t.get("nombre") == "latido-salud" for t in cuerpo["tareas_programadas"]
    )


def test_leer_latido_no_lanza_sin_redis():
    """`leer_latido()` informa del fallo de Redis en vez de propagar la excepcion."""
    from app.tasks.salud_tasks import leer_latido

    resultado = leer_latido()

    assert isinstance(resultado, dict)
    assert "ok" in resultado
    assert "detalle" in resultado


def test_el_beat_planifica_el_latido_de_salud():
    """La periodicidad del latido esta en el `beat_schedule` de Celery."""
    from app.core.celery_app import celery_app

    agenda = celery_app.conf.beat_schedule or {}

    assert "latido-salud" in agenda
    assert agenda["latido-salud"]["task"] == "app.tasks.salud_tasks.registrar_latido"


# ---------------------------------------------------------------------------
# 6. XSS almacenado en el renderizador Markdown (guard estatico sobre el JS)
# ---------------------------------------------------------------------------
def test_el_renderizador_markdown_filtra_los_esquemas_peligrosos():
    """El JS de Markdown usa lista blanca de esquemas y escapa comillas.

    Guard ESTATICO sobre el fuente: no hay motor JavaScript disponible en
    esta suite, asi que se comprueba la presencia de las invariantes de
    seguridad, no el comportamiento en un navegador.
    """
    fuente = (RAIZ / "app" / "static" / "js" / "htmx-events.js").read_text(
        encoding="utf-8"
    )

    assert "_urlMarkdownSegura" in fuente
    assert "'http:'" in fuente and "'https:'" in fuente and "'mailto:'" in fuente
    assert "rel=\"noopener noreferrer\"" in fuente
    # El href ya no se interpola sin validar.
    assert 'href="$2"' not in fuente
    # Se escapan las comillas antes de construir el HTML.
    assert ".replace(/\"/g, '&quot;')" in fuente
    assert ".replace(/'/g, '&#39;')" in fuente


def test_el_html_del_modal_de_ticket_no_escapa_el_titulo(db_session):
    """El modal de detalle escapa el contenido (regresion de V1.005, se mantiene)."""
    from app.core.security import hash_password
    from app.models.estado import Estado
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia
    from app.models.usuario import RolUsuario, Usuario
    from app.templates.tickets.detalle_modal import render_detalle_modal

    usuario = Usuario(
        username="v1006_escape",
        email="v1006_escape@example.test",
        nombre_completo="Usuario de regresión",
        hashed_password=hash_password("Clave-local-de-regresion-2026"),
        rol=RolUsuario.ADMINISTRADOR,
        is_active=True,
    )
    estado = Estado(nombre="V1006 escape", color="#334155", orden=101)
    db_session.add_all([usuario, estado])
    db_session.flush()

    ticket = Ticket(
        codigo="V1006-ESC-001",
        titulo='<script>alert("titulo")</script>',
        descripcion='<img src=x onerror="alert(1)">',
        tipo=TipoIncidencia.INCIDENCIA,
        prioridad=Prioridad.MEDIA,
        estado=estado,
        creador=usuario,
        datos_catalogo={},
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    html = render_detalle_modal(
        ticket=ticket,
        estados=[estado],
        comentarios=[],
        adjuntos=[],
        checklists=[],
        usuario=usuario,
    )

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html


# ---------------------------------------------------------------------------
# 7. Documentacion y configuracion declaradas
# ---------------------------------------------------------------------------
def test_env_example_declara_las_variables_que_el_codigo_usa():
    """`.env.example` documenta las variables leidas por la aplicacion."""
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")

    for variable in (
        "SECRET_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "EXPOSE_API_DOCS",
        "SECURITY_CSP",
        "APP_TIMEZONE",
        "AUTO_INIT_DB",
    ):
        assert re.search(rf"^\s*{variable}\s*=", texto, re.M), variable


def test_el_readme_documenta_rutas_que_existen_en_el_openapi():
    """Las rutas de la tabla de endpoints del README existen de verdad."""
    from app.main import app

    esquema = app.openapi().get("paths", {})
    # ``/docs`` y ``/redoc`` las sirve FastAPI pero no aparecen en el
    # esquema OpenAPI: se contrastan contra las rutas registradas.
    rutas_app = {getattr(ruta, "path", "") for ruta in app.routes}
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    coincidencias = re.findall(
        r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`",
        texto,
        flags=re.M | re.I,
    )

    assert coincidencias, "la tabla de endpoints del README no se encontro"
    rotas = []
    for metodo, ruta in coincidencias:
        operaciones = esquema.get(ruta)
        if operaciones is None:
            if ruta not in rutas_app:
                rotas.append(f"{metodo.upper()} {ruta}: la ruta no existe")
            continue
        if metodo.lower() not in operaciones:
            rotas.append(f"{metodo.upper()} {ruta}: el metodo no existe")
    assert not rotas, rotas
