"""Tests de humo para el servicio Kanban (validación de transiciones ITSM)."""
import os
import sys
from pathlib import Path

# Forzar SQLite para los tests (no requiere Postgres)
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_itsm.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-12345678")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "admin123")

# Agregar el root del proyecto al path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base, get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado, CategoriaEstado
from app.models.transicion import Transicion, RolRequerido
from app.models.ticket import Ticket, PrioridadTicket

# Motor SQLite en memoria para tests aislados
engine_test = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine_test, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Crea las tablas, corre seeds mínimos y entrega una sesión."""
    Base.metadata.create_all(bind=engine_test)
    db = TestingSessionLocal()
    try:
        _seed_minimo(db)
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine_test)


def _seed_minimo(db):
    """Seed mínimo para tests: admin, 2 estados, 1 transición, 1 ticket."""
    admin = Usuario(
        username="admin", email="admin@test.com", nombre_completo="Admin",
        password_hash=hash_password("admin123"), rol=RolUsuario.ADMINISTRADOR, activo=True,
    )
    db.add(admin)
    db.flush()

    s1 = Estado(nombre="Pendiente", orden=1, categoria=CategoriaEstado.PENDIENTE, color="#64748b",
                es_inicial=True, es_final=False, activo=True)
    s2 = Estado(nombre="En curso", orden=2, categoria=CategoriaEstado.EN_PROGRESO, color="#2563eb",
                es_inicial=False, es_final=False, activo=True)
    s3 = Estado(nombre="Cerrado", orden=3, categoria=CategoriaEstado.CERRADO, color="#16a34a",
                es_inicial=False, es_final=True, activo=True)
    db.add_all([s1, s2, s3])
    db.flush()

    db.add(Transicion(
        origen_id=s1.id, destino_id=s2.id, nombre="Iniciar",
        rol_requerido=RolRequerido.AGENTE, requiere_comentario=False, activo=True,
    ))
    db.add(Transicion(
        origen_id=s2.id, destino_id=s3.id, nombre="Cerrar",
        rol_requerido=RolRequerido.AGENTE_SENIOR, requiere_comentario=True, activo=True,
    ))

    db.add(Ticket(
        codigo="TKT-00001", titulo="Ticket de prueba", descripcion="",
        estado_id=s1.id, prioridad=PrioridadTicket.MEDIA,
        creador_id=admin.id, posicion=0,
    ))
    db.commit()


def test_transicion_legal_admin(db_session):
    """Admin puede mover un ticket de Pendiente a En curso (regla sin comentario)."""
    from app.services.kanban_service import mover_ticket

    admin = db_session.query(Usuario).filter(Usuario.username == "admin").one()
    ticket = db_session.query(Ticket).first()
    s2 = db_session.query(Estado).filter(Estado.nombre == "En curso").one()

    result = mover_ticket(
        db=db_session,
        ticket_id=ticket.id,
        estado_destino_id=s2.id,
        usuario=admin,
        nueva_posicion=0,
        comentario="",
    )
    assert result["estado_id"] == s2.id
    # Verificar que se creó un evento de auditoría
    from app.models.auditoria import AuditoriaEvento, TipoEvento
    eventos = db_session.query(AuditoriaEvento).filter(AuditoriaEvento.ticket_id == ticket.id).all()
    assert len(eventos) == 1
    assert eventos[0].tipo == TipoEvento.ESTADO_CAMBIADO
    assert eventos[0].actor_username == "admin"


def test_transicion_ilegal(db_session):
    """Saltarse una transición debe fallar (Pendiente → Cerrado no existe)."""
    from fastapi import HTTPException
    from app.services.kanban_service import mover_ticket

    admin = db_session.query(Usuario).filter(Usuario.username == "admin").one()
    ticket = db_session.query(Ticket).first()
    s3 = db_session.query(Estado).filter(Estado.nombre == "Cerrado").one()

    with pytest.raises(HTTPException) as exc_info:
        mover_ticket(
            db=db_session, ticket_id=ticket.id, estado_destino_id=s3.id,
            usuario=admin, nueva_posicion=0, comentario="",
        )
    assert exc_info.value.status_code == 422


def test_comentario_requerido(db_session):
    """Para cerrar un ticket (regla con requiere_comentario=True) se exige comentario."""
    from fastapi import HTTPException
    from app.services.kanban_service import mover_ticket

    admin = db_session.query(Usuario).filter(Usuario.username == "admin").one()
    ticket = db_session.query(Ticket).first()
    s2 = db_session.query(Estado).filter(Estado.nombre == "En curso").one()

    # Mover primero a En curso
    mover_ticket(db=db_session, ticket_id=ticket.id, estado_destino_id=s2.id,
                 usuario=admin, nueva_posicion=0, comentario="")

    # Intentar cerrar SIN comentario: debe fallar
    s3 = db_session.query(Estado).filter(Estado.nombre == "Cerrado").one()
    with pytest.raises(HTTPException) as exc_info:
        mover_ticket(db=db_session, ticket_id=ticket.id, estado_destino_id=s3.id,
                     usuario=admin, nueva_posicion=0, comentario="")
    assert exc_info.value.status_code == 422

    # Con comentario: debe funcionar
    result = mover_ticket(db=db_session, ticket_id=ticket.id, estado_destino_id=s3.id,
                          usuario=admin, nueva_posicion=0, comentario="QA verificado, todo OK")
    assert result["estado_id"] == s3.id


def test_auditoria_obligatoria(db_session):
    """Toda transición exitosa DEBE dejar un evento de auditoría."""
    from app.services.kanban_service import mover_ticket
    from app.models.auditoria import AuditoriaEvento, TipoEvento

    admin = db_session.query(Usuario).filter(Usuario.username == "admin").one()
    ticket = db_session.query(Ticket).first()
    s2 = db_session.query(Estado).filter(Estado.nombre == "En curso").one()

    n_inicial = db_session.query(AuditoriaEvento).filter(AuditoriaEvento.ticket_id == ticket.id).count()
    mover_ticket(db=db_session, ticket_id=ticket.id, estado_destino_id=s2.id,
                 usuario=admin, nueva_posicion=0, comentario="")
    n_final = db_session.query(AuditoriaEvento).filter(AuditoriaEvento.ticket_id == ticket.id).count()

    assert n_final == n_inicial + 1
    ultimo = db_session.query(AuditoriaEvento).filter(AuditoriaEvento.ticket_id == ticket.id).order_by(AuditoriaEvento.id.desc()).first()
    assert ultimo.tipo == TipoEvento.ESTADO_CAMBIADO
    assert "En curso" in ultimo.valor_nuevo
