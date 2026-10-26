"""
Regresiones de logica de negocio de V1.007 (servicios, tareas, modelos y BD).

Cada test cubre un comportamiento OBSERVABLE de los defectos corregidos:

1. La auditoria registrada con ``registrar_auditoria(commit=True)`` no debe
   perderse al cerrar la sesion (el ``commit=True`` historicamente solo
   hacia ``flush()``).
2. Un ticket creado directamente en un estado FINAL debe quedar cerrado:
   ``fecha_completado`` registrada, ``fecha_cumplida`` y ``sla_cumplido=1``.
   Antes quedaba con ``fecha_completado`` NULL y ``sla_cumplido=-1``, y el
   beat lo marcaba despues como SLA incumplido.
3. Un ticket creado en un estado terminal de ENTREGA (``es_entrega=True``)
   debe registrarse en el reporte diario de entregas.
4. El listado de tickets no debe hacer una consulta por ticket (N+1) al
   leer las etiquetas.
5. Los triggers de deadline no deben hacer una consulta por ticket (N+1)
   para resolver idempotencia y destinatarios.
6. Una migracion cuyo indice no se puede crear debe quedar VISIBLE en las
   estadisticas (antes se registraba a nivel ``debug`` y se perdia).

Todos operan sobre la base SQLite temporal de la suite (ver
``tests/conftest.py``): nunca leen ni escriben en la base de datos de
produccion.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest


# ---------------------------------------------------------------------------
# Utilidades compartidas
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_and_schema():
    """Prepara el esquema en la SQLite temporal de la suite."""
    import app.models  # noqa: F401  (registra las tablas en Base.metadata)
    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(app_and_schema):
    """Sesion SQLAlchemy sobre la SQLite temporal de la suite."""
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def contar_selects(engine):
    """Cuenta las sentencias SELECT que se ejecutan dentro del bloque."""
    from sqlalchemy import event

    contador = {"total": 0}

    def _al_ejecutar(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            contador["total"] += 1

    event.listen(engine, "before_cursor_execute", _al_ejecutar)
    try:
        yield contador
    finally:
        event.remove(engine, "before_cursor_execute", _al_ejecutar)


def _crear_usuario(db, username, rol):
    """Crea un usuario persistente y lo devuelve."""
    from app.core.security import hash_password
    from app.models.usuario import Usuario

    usuario = Usuario(
        username=username,
        email=f"{username}@example.test",
        nombre_completo=f"Usuario {username}",
        hashed_password=hash_password("Clave-local-de-regresion-2026"),
        rol=rol,
        is_active=True,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def _crear_estado(db, nombre, **kwargs):
    """Crea un estado persistente y lo devuelve."""
    from app.models.estado import Estado

    estado = Estado(nombre=nombre, color="#334155", **kwargs)
    db.add(estado)
    db.commit()
    db.refresh(estado)
    return estado


def _obtener_o_crear_estado(db, nombre, **kwargs):
    """Devuelve el estado con ese nombre, creandolo si no existe.

    El nombre de los estados es UNIQUE y la base de la suite es
    compartida, asi que algunos estados canonicos (p.ej. 'Produccion OK')
    pueden ya existir.
    """
    from app.models.estado import Estado

    existente = db.query(Estado).filter(Estado.nombre == nombre).first()
    if existente:
        return existente
    return _crear_estado(db, nombre, **kwargs)


# ---------------------------------------------------------------------------
# 1. La auditoria no se pierde al cerrar la sesion
# ---------------------------------------------------------------------------
def test_auditoria_de_la_plantilla_sobrevive_al_cierre_de_la_sesion(db_session):
    """``guardar_plantilla`` debe dejar la auditoria persistida.

    ``registrar_auditoria(commit=True)`` solo hace ``flush()``: sin un
    ``commit`` explicito el INSERT se pierde cuando la sesion se cierra
    (que es exactamente lo que hace ``get_db()`` al terminar el request).
    """
    from app.db.session import SessionLocal
    from app.models.auditoria import Auditoria
    from app.services.reporte_entregas_service import guardar_plantilla

    guardar_plantilla(
        db_session,
        habilitado=True,
        asunto="Asunto de prueba",
        cuerpo_html="<p>html</p>",
        cuerpo_texto="texto",
        firma="Equipo",
        actor_id=None,
    )

    # Sesion nueva: lo que quedo realmente en la base de datos.
    otra = SessionLocal()
    try:
        filas = otra.query(Auditoria).filter(
            Auditoria.accion == "REPORTE_ENTREGAS_PLANTILLA_EDITADA"
        ).count()
    finally:
        otra.close()

    assert filas == 1, "La auditoria de la plantilla no debe perderse"


def test_registrar_auditoria_solo_hace_flush(db_session):
    """Documenta el comportamiento real de ``registrar_auditoria``:
    ``commit=True`` hace ``flush()``, no ``commit()``. Por eso los
    llamadores deben hacer ``db.commit()`` despues.
    """
    from app.db.session import SessionLocal
    from app.models.auditoria import Auditoria
    from app.services.auditoria_service import registrar_auditoria

    registrar_auditoria(
        db=db_session,
        ticket_id=None,
        usuario_id=None,
        accion="V1007_SIN_COMMIT",
        commit=True,
    )
    # Visible en la sesion actual...
    assert db_session.query(Auditoria).filter(
        Auditoria.accion == "V1007_SIN_COMMIT"
    ).count() == 1

    # ...pero no persistida si nadie hace commit.
    otra = SessionLocal()
    try:
        persistidas = otra.query(Auditoria).filter(
            Auditoria.accion == "V1007_SIN_COMMIT"
        ).count()
    finally:
        otra.close()
    assert persistidas == 0


# ---------------------------------------------------------------------------
# 2. Ticket creado directamente en un estado final
# ---------------------------------------------------------------------------
def test_ticket_creado_en_estado_final_queda_cerrado(db_session):
    """Un ticket abierto en un estado final debe quedar cerrado."""
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    admin = _crear_usuario(db_session, "v1007_admin", RolUsuario.ADMINISTRADOR)
    # Nombre canonico: es la regla "Produccion OK fuerza cumplimiento".
    estado_final = _obtener_o_crear_estado(
        db_session,
        "Produccion OK",
        es_inicial=False,
        es_final=True,
        sla_horas=None,
        orden=91,
    )

    ticket = TicketService(db_session).crear_ticket(
        {"titulo": "Ticket creado en estado final", "estado_id": estado_final.id},
        admin,
    )
    db_session.refresh(ticket)

    assert ticket.fecha_completado is not None, (
        "Todo estado final debe registrar fecha_completado"
    )
    assert ticket.sla_cumplido == 1, (
        "Un ticket creado en un estado final nace con el SLA cumplido, no pendiente"
    )
    assert ticket.fecha_cumplida is True


def test_recalcular_sla_no_marca_vencido_un_ticket_creado_en_estado_final(db_session):
    """El beat (cada 5 min) recalcula el SLA: no debe degradar a 'vencido'
    un ticket que ya estaba en un estado final.
    """
    from app.models.usuario import RolUsuario
    from app.services.sla_service import SLAService
    from app.services.ticket_service import TicketService

    admin = _crear_usuario(db_session, "v1007_admin2", RolUsuario.ADMINISTRADOR)
    estado_final = _crear_estado(
        db_session,
        "Cerrado V1007",
        es_inicial=False,
        es_final=True,
        sla_horas=None,
        orden=92,
    )

    ticket = TicketService(db_session).crear_ticket(
        {"titulo": "Ticket final recalculado", "estado_id": estado_final.id},
        admin,
    )
    ticket_id = ticket.id

    SLAService(db_session).recalcular_ticket(ticket_id)
    db_session.refresh(ticket)

    assert ticket.sla_cumplido == 1, (
        "El recalculo del SLA no debe marcar como vencido un ticket ya final"
    )


def test_ticket_creado_en_estado_normal_sigue_pendiente_de_sla(db_session):
    """El cambio NO debe alterar el caso normal: un ticket creado en un
    estado no final nace con el SLA pendiente (-1) y sin fecha de cierre.
    """
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    admin = _crear_usuario(db_session, "v1007_admin3", RolUsuario.ADMINISTRADOR)
    estado_inicial = _crear_estado(
        db_session,
        "BackLog V1007",
        es_inicial=True,
        es_final=False,
        sla_horas=24,
        orden=93,
    )

    ticket = TicketService(db_session).crear_ticket(
        {"titulo": "Ticket normal", "estado_id": estado_inicial.id},
        admin,
    )
    db_session.refresh(ticket)

    assert ticket.sla_cumplido == -1
    assert ticket.fecha_completado is None
    assert ticket.fecha_vencimiento_sla is not None


# ---------------------------------------------------------------------------
# 3. Ticket creado en un estado terminal de entrega
# ---------------------------------------------------------------------------
def test_ticket_creado_en_estado_de_entrega_encola_el_registro(db_session, monkeypatch):
    """Abrir un ticket en un estado ``es_entrega=True`` debe registrarlo en
    el reporte diario de entregas, igual que mover un ticket a ese estado.
    """
    from app.models.usuario import RolUsuario
    from app.services.ticket_service import TicketService

    admin = _crear_usuario(db_session, "v1007_admin4", RolUsuario.ADMINISTRADOR)
    estado_entrega = _crear_estado(
        db_session,
        "Entregado V1007",
        es_inicial=False,
        es_final=True,
        sla_horas=None,
        es_entrega=True,
        orden=94,
    )

    llamadas = {}

    class _TaskFalsa:
        id = "task-falsa"

        @staticmethod
        def delay(ticket_id, historial_estado_id):
            llamadas["args"] = (ticket_id, historial_estado_id)
            return _TaskFalsa()

    import app.tasks.entregas as modulo_entregas

    monkeypatch.setattr(modulo_entregas, "registrar_entrega_diaria", _TaskFalsa)

    ticket = TicketService(db_session).crear_ticket(
        {"titulo": "Ticket de entrega", "estado_id": estado_entrega.id},
        admin,
    )

    assert "args" in llamadas, "Debe encolarse el registro de entrega diaria"
    ticket_id, historial_id = llamadas["args"]
    assert ticket_id == ticket.id
    assert historial_id is not None

    # El historial inicial es el que documenta la entrada al estado.
    from app.models.ticket import HistorialEstado

    historial = db_session.query(HistorialEstado).filter(
        HistorialEstado.id == historial_id
    ).first()
    assert historial is not None
    assert historial.estado_destino_id == estado_entrega.id
    assert historial.estado_origen_id is None


# ---------------------------------------------------------------------------
# 4. Listado de tickets sin N+1 de etiquetas
# ---------------------------------------------------------------------------
def test_listado_de_tickets_no_hace_una_consulta_por_ticket(app_and_schema, db_session):
    """Leer las etiquetas de un listado de tickets no debe generar un
    SELECT por ticket (N+1)."""
    from app.models.etiqueta import Etiqueta
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario

    usuario = _crear_usuario(db_session, "v1007_admin5", RolUsuario.ADMINISTRADOR)
    estado = _crear_estado(
        db_session, "Kanban V1007", es_inicial=True, es_final=False,
        sla_horas=24, orden=95,
    )
    etiqueta = Etiqueta(nombre="critica-v1007", color="#dc2626")
    db_session.add(etiqueta)
    db_session.commit()
    db_session.refresh(etiqueta)

    tickets = []
    for i in range(12):
        t = Ticket(
            codigo=f"V1007-{i:03d}",
            titulo=f"Ticket {i}",
            descripcion="d",
            estado_id=estado.id,
            creador_id=usuario.id,
            asignado_id=usuario.id,
        )
        db_session.add(t)
        tickets.append(t)
    db_session.commit()
    etiquetas = [etiqueta]
    for t in tickets:
        t.etiquetas = etiquetas
    db_session.commit()

    db_session.expunge_all()

    with contar_selects(app_and_schema) as contador:
        filas = db_session.query(Ticket).filter(
            Ticket.codigo.like("V1007-%")
        ).all()
        for t in filas:
            _ = t.etiquetas
        total = contador["total"]

    assert len(filas) == 12
    assert total <= 4, (
        f"El listado hizo {total} SELECT para 12 tickets: es un N+1 "
        f"(esperado: 1 consulta del listado + 1 de las etiquetas)"
    )


# ---------------------------------------------------------------------------
# 5. Triggers de deadline sin N+1
# ---------------------------------------------------------------------------
def test_destinatarios_de_un_lote_no_escalan_con_el_numero_de_tickets(app_and_schema, db_session):
    """Resolver los destinatarios de N tickets debe costar 1 consulta de
    usuarios, no una por ticket."""
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario
    from app.services.deadline_notifier import _destinatarios_por_ticket

    usuario = _crear_usuario(db_session, "v1007_admin6", RolUsuario.ADMINISTRADOR)
    estado = _crear_estado(
        db_session, "Vencidos V1007", es_inicial=True, es_final=False,
        sla_horas=24, orden=96,
    )
    for i in range(10):
        db_session.add(Ticket(
            codigo=f"V1007-V-{i:03d}",
            titulo=f"Vencido {i}",
            descripcion="d",
            estado_id=estado.id,
            creador_id=usuario.id,
            asignado_id=usuario.id,
        ))
    db_session.commit()
    db_session.expunge_all()

    # Los triggers cargan los tickets con ``selectinload(Ticket.miembros)``:
    # los miembros ya vienen cargados y lo que se mide a continuacion es
    # el coste del helper (una consulta de usuarios para todo el lote).
    from sqlalchemy.orm import selectinload

    tickets = db_session.query(Ticket).options(
        selectinload(Ticket.miembros)
    ).filter(
        Ticket.codigo.like("V1007-V-%")
    ).all()

    with contar_selects(app_and_schema) as contador:
        mapa = _destinatarios_por_ticket(db_session, tickets)
        total = contador["total"]

    assert len(mapa) == 10
    assert all(mapa[t.id] for t in tickets)
    assert total <= 2, (
        f"Resolver destinatarios de 10 tickets costó {total} SELECT "
        f"(esperado: 1 de usuarios para todo el lote)"
    )


def test_ids_ya_notificados_se_resuelve_en_una_consulta(app_and_schema, db_session):
    """La comprobacion de idempotencia debe resolverse en 1 consulta para
    todo el lote, no una por ticket."""
    from app.models.auditoria import Auditoria
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario
    from app.services.deadline_notifier import _ids_ya_notificados, _ya_notificado_hoy

    estado = _crear_estado(
        db_session, "Idem V1007", es_inicial=True, es_final=False,
        sla_horas=24, orden=97,
    )
    usuario = _crear_usuario(db_session, "v1007_admin7", RolUsuario.ADMINISTRADOR)
    tickets = []
    for i in range(8):
        t = Ticket(
            codigo=f"V1007-I-{i:03d}",
            titulo=f"Idem {i}",
            descripcion="d",
            estado_id=estado.id,
            creador_id=usuario.id,
        )
        db_session.add(t)
        tickets.append(t)
    db_session.commit()
    db_session.refresh(tickets[0])

    db_session.add(Auditoria(
        ticket_id=tickets[0].id,
        usuario_id=None,
        accion="deadline_trigger:deadline_missed",
        valor_nuevo={"trigger": "deadline_missed"},
    ))
    db_session.commit()
    db_session.expunge_all()

    ids = [t.id for t in db_session.query(Ticket).filter(
        Ticket.codigo.like("V1007-I-%")
    ).all()]

    with contar_selects(app_and_schema) as contador:
        ya = _ids_ya_notificados(db_session, ids, "deadline_missed")
        total = contador["total"]

    assert total == 1, f"La idempotencia costo {total} SELECT (esperado: 1)"
    assert tickets[0].id in ya
    assert len(ya) == 1

    # Con el conjunto precalculado, la comprobacion por ticket no consulta.
    with contar_selects(app_and_schema) as contador:
        assert _ya_notificado_hoy(db_session, tickets[0].id, "deadline_missed", ya) is True
        assert _ya_notificado_hoy(db_session, ids[1], "deadline_missed", ya) is False
        total = contador["total"]

    assert total == 0, "Con el lote precalculado no debe haber consultas"


# ---------------------------------------------------------------------------
# 7. SAVEPOINT al asignar etapas: no debe tirar el trabajo del llamador
# ---------------------------------------------------------------------------
def test_fallo_al_asignar_etapas_no_descarta_el_trabajo_del_llamador(db_session, monkeypatch):
    """Un fallo al asignar las etapas NO debe deshacer lo que el llamador
    tenía pendiente: con ``db.rollback()`` a secas se perdía el INSERT del
    ticket (y el historial y la auditoría) mientras la API respondía OK.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.etapa_proyecto import EtapaProyecto
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario
    from app.services.etapa_service import EtapaService

    usuario = _crear_usuario(db_session, "v1007_admin8", RolUsuario.ADMINISTRADOR)
    estado = _crear_estado(
        db_session, "Etapas V1007", es_inicial=True, es_final=False,
        sla_horas=24, orden=98,
    )
    db_session.add(EtapaProyecto(
        # ``orden`` es UNIQUE y el seed ya crea las etapas 1..10: se usa un
        # valor libre para que el INSERT de esta etapa no choque por el
        # indice (el fallo que se quiere provocar en la prueba es el del
        # flush de la ASIGNACION, no el de esta fila).
        codigo="V1007-ETAPA", nombre="Etapa V1007", orden=100, activo=1,
    ))
    db_session.commit()

    # Trabajo pendiente del llamador: el INSERT del ticket (ya flushed).
    ticket = Ticket(
        codigo="V1007-SP-001",
        titulo="Ticket con SAVEPOINT",
        descripcion="d",
        estado_id=estado.id,
        creador_id=usuario.id,
    )
    db_session.add(ticket)
    db_session.flush()

    def _flush_fallido(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("choque simulado"))

    monkeypatch.setattr(db_session, "flush", _flush_fallido)
    EtapaService(db_session).asignar_etapas_iniciales(ticket)
    monkeypatch.undo()

    # El ticket del llamador sigue vivo.
    assert db_session.query(Ticket).filter(
        Ticket.codigo == "V1007-SP-001"
    ).count() == 1, (
        "El fallo al asignar etapas no debe descartar el trabajo pendiente "
        "del llamador"
    )


# ---------------------------------------------------------------------------
# 8. El recalculo masivo de SLA no hace una consulta por ticket
# ---------------------------------------------------------------------------
def test_recalculo_masivo_de_sla_no_consulta_ticket_por_ticket(app_and_schema, db_session):
    """El beat recalcula el SLA cada 5 minutos: los tickets ya vienen
    cargados del lote y se confirman una sola vez."""
    from datetime import timedelta

    from app.core.timezone import now_utc
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario
    from app.services.sla_service import SLAService

    usuario = _crear_usuario(db_session, "v1007_admin9", RolUsuario.ADMINISTRADOR)
    estado = _crear_estado(
        db_session, "SLA V1007", es_inicial=True, es_final=False,
        sla_horas=24, orden=99,
    )
    vencida = now_utc() - timedelta(hours=2)
    for i in range(5):
        db_session.add(Ticket(
            codigo=f"V1007-SLA-{i:03d}",
            titulo=f"Vencido {i}",
            descripcion="d",
            estado_id=estado.id,
            creador_id=usuario.id,
            sla_cumplido=-1,
            fecha_vencimiento_sla=vencida,
        ))
    db_session.commit()

    tickets = db_session.query(Ticket).filter(
        Ticket.codigo.like("V1007-SLA-%")
    ).all()
    assert len(tickets) == 5

    with contar_selects(app_and_schema) as contador:
        procesados = SLAService(db_session).recalcular_tickets(tickets)
        total = contador["total"]

    assert procesados == 5
    assert total == 0, (
        f"El recalculo masivo hizo {total} SELECT con los tickets ya cargados "
        f"(esperado: 0; antes consultaba y confirmaba uno por ticket)"
    )

    db_session.expire_all()
    for t in db_session.query(Ticket).filter(
        Ticket.codigo.like("V1007-SLA-%")
    ).all():
        assert t.sla_cumplido == 0, "Un ticket vencido debe quedar como no cumplido"


# ---------------------------------------------------------------------------
# 6. Migraciones: los indices que fallan quedan visibles
# ---------------------------------------------------------------------------
def test_migraciones_reportan_los_indices_que_no_se_pueden_crear(tmp_path):
    """Un indice que no se puede crear debe quedar registrado en las
    estadisticas (antes solo se registraba a nivel ``debug``)."""
    from sqlalchemy import create_engine, text

    from app.db import migrations

    motor = create_engine(f"sqlite:///{tmp_path / 'deriva.sqlite'}")
    # Tabla con un esquema ANTERIOR: sin la columna ``tipo`` que usan los
    # indices ix_ref_origen_tipo / ix_ref_destino_tipo.
    with motor.begin() as conn:
        conn.execute(text(
            "CREATE TABLE ticket_referencias ("
            "id INTEGER PRIMARY KEY, "
            "ticket_origen_id INTEGER, "
            "ticket_referenciado_id INTEGER)"
        ))

    stats = migrations.apply_migrations(motor)

    assert stats["index_errors"] >= 1, (
        "Un indice que no se pudo crear debe quedar contabilizado"
    )

    # El indice que falla NO debe tumbar el arranque: el esquema sirve.
    assert migrations.verificar_esquema(motor) == 0
