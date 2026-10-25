"""Regresiones deterministas para los cambios de seguridad de V1.005."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient


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


def test_detalle_modal_autoescape_titulo_y_descripcion(db_session):
    """El modal escapa titulo y descripcion antes de insertarlos en HTML."""
    from app.core.security import hash_password
    from app.models.estado import Estado
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia
    from app.models.usuario import RolUsuario, Usuario
    from app.templates.tickets.detalle_modal import render_detalle_modal

    usuario = Usuario(
        username="v1005_escape",
        email="v1005_escape@example.test",
        nombre_completo="Usuario de regresión",
        hashed_password=hash_password("Clave-local-de-regresion-2026"),
        rol=RolUsuario.ADMINISTRADOR,
        is_active=True,
    )
    estado = Estado(nombre="Estado regresión escape", color="#334155", orden=99)
    db_session.add_all([usuario, estado])
    db_session.flush()

    ticket = Ticket(
        codigo="V1005-ESC-001",
        titulo='<script>alert("titulo")</script>',
        descripcion='<img src=x onerror="alert(1)">',
        tipo=TipoIncidencia.INCIDENCIA,
        prioridad=Prioridad.MEDIA,
        estado=estado,
        creador=usuario,
        asignado=None,
        datos_catalogo={},
        descripcion_md=False,
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
    assert "&lt;img src=x" in html


def test_endpoint_diag_tickets_retirado(local_client, app_and_schema):
    """El diagnostico que exponia tickets no existe ni en rutas ni en OpenAPI."""
    app, _engine = app_and_schema

    assert all(getattr(route, "path", None) != "/_diag/tickets" for route in app.routes)
    assert "/_diag/tickets" not in app.openapi().get("paths", {})

    response = local_client.get("/_diag/tickets")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        (
            "postgresql://grm:clave-secreta@db.example.test:5432/bitacora",
            "postgresql://grm:***@db.example.test:5432/bitacora",
        ),
        (
            "postgresql://db.example.test:5432/bitacora",
            "postgresql://db.example.test:5432/bitacora",
        ),
    ],
)
def test_enmascarar_url_db_oculta_solo_la_contrasena(url, esperado):
    """La URL enmascarada conserva esquema, usuario, servidor y base."""
    from app.core.config import enmascarar_url_db

    resultado = enmascarar_url_db(url)

    assert resultado == esperado
    assert "clave-secreta" not in resultado


def test_reporte_diario_filtra_por_fecha_con_func_date(db_session):
    """func.date selecciona el dia completo y excluye el dia anterior."""
    from app.models.reporte_entregas import ReporteEntregaDiaria, ReportePlantilla
    from app.tasks.entregas import generar_reporte_diario

    db_session.query(ReporteEntregaDiaria).delete()
    plantilla_existente = (
        db_session.query(ReportePlantilla).filter(ReportePlantilla.id == 1).first()
    )
    if plantilla_existente:
        plantilla_existente.habilitado = False
    else:
        db_session.add(
            ReportePlantilla(
                id=1,
                habilitado=False,
                asunto="Reporte local de regresión",
                cuerpo_html="contenido local",
                cuerpo_texto="contenido local",
                firma="",
            )
        )

    db_session.add_all(
        [
            ReporteEntregaDiaria(
                ticket_codigo="V1005-DIA-001",
                estado_destino_nombre="Entregado",
                fecha_entrega=datetime(2026, 10, 24, 0, 5),
            ),
            ReporteEntregaDiaria(
                ticket_codigo="V1005-DIA-002",
                estado_destino_nombre="Resuelto",
                fecha_entrega=datetime(2026, 10, 24, 18, 45),
            ),
            ReporteEntregaDiaria(
                ticket_codigo="V1005-DIA-003",
                estado_destino_nombre="Entregado",
                fecha_entrega=datetime(2026, 10, 23, 23, 55),
            ),
        ]
    )
    db_session.commit()

    resultado = generar_reporte_diario.run(fecha_objetivo="2026-10-24")

    assert resultado["ok"] is True
    assert resultado["cantidad"] == 2
    assert resultado["skipped_reason"] == "plantilla_deshabilitada"


def test_tableros_enlaza_slug_publico_solo_para_tableros_publicos(
    db_session, local_client
):
    """Un tablero de espacio no recibe un enlace que siempre responderia 404."""
    from app.core.security import hash_password
    from app.models.espacio import Espacio, Tablero
    from app.models.usuario import RolUsuario, Usuario

    usuario = Usuario(
        username="v1005_tableros",
        email="v1005_tableros@example.test",
        nombre_completo="Administrador de regresión",
        hashed_password=hash_password("Clave-local-de-regresion-2026"),
        rol=RolUsuario.ADMINISTRADOR,
        is_active=True,
    )
    db_session.add(usuario)
    db_session.flush()

    espacio = Espacio(
        nombre="Espacio de regresión",
        plan="gratis",
        es_publico=False,
        propietario=usuario,
    )
    db_session.add(espacio)
    db_session.flush()

    db_session.add_all(
        [
            Tablero(
                nombre="Tablero público",
                espacio=espacio,
                propietario=usuario,
                visibilidad="publico",
                slug_publico="v1005-publico",
            ),
            Tablero(
                nombre="Tablero de espacio",
                espacio=espacio,
                propietario=usuario,
                visibilidad="espacio",
                slug_publico="v1005-espacio",
            ),
        ]
    )
    db_session.commit()

    login = local_client.post(
        "/api/v1/auth/login",
        json={
            "username": "v1005_tableros",
            "password": "Clave-local-de-regresion-2026",
        },
    )
    assert login.status_code == 200, login.text

    response = local_client.get("/tableros")
    assert response.status_code == 200, response.text
    assert 'href="/p/v1005-publico"' in response.text
    assert 'href="/p/v1005-espacio"' not in response.text
