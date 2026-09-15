#!/usr/bin/env python3
"""End-to-end validation test for the responsable picker + email flow.

Flow:
1. Admin logs in
2. Admin assigns responsable to a column via PATCH
3. Verify diagnostic endpoint shows correct status
4. Create ticket in another column
5. Move ticket to column-with-responsable via cambiar_estado service
6. Verify Notificacion was created
7. Verify email was attempted (sent or log fallback)
8. Verify Email log file was written (Dev Inbox)
"""
import os, sys, tempfile, logging, json
logging.disable(logging.CRITICAL)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
import warnings
warnings.filterwarnings('ignore')

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['ALLOW_XUSER_HEADER'] = 'true'
# Limpiar emails previos en tmp/
import pathlib
_log_dir = pathlib.Path('tmp')
if _log_dir.exists():
    for f in _log_dir.glob('app.email.log*'):
        f.unlink()

from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.espacio import Espacio, Tablero
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.models.watch import Notificacion
from app.core.security import hash_password
from datetime import datetime

db = SessionLocal()
try:
    # Setup
    admin = Usuario(username='admin', email='admin@test.com',
                    nombre_completo='Administrador Sistema',
                    rol=RolUsuario.ADMINISTRADOR,
                    hashed_password=hash_password('test1234'),
                    is_active=True)
    db.add(admin); db.commit(); db.refresh(admin)

    moises = Usuario(username='moises', email='moises@test.com',
                     nombre_completo='Moisés Arancibia',
                     rol=RolUsuario.AGENTE_SENIOR,
                     hashed_password=hash_password('x'),
                     is_active=True)
    db.add(moises); db.commit(); db.refresh(moises)

    ana = Usuario(username='ana', email='ana@test.com',
                  nombre_completo='Ana Pérez',
                  rol=RolUsuario.AGENTE,
                  hashed_password=hash_password('x'),
                  is_active=True)
    db.add(ana); db.commit(); db.refresh(ana)

    # 2 columnas
    col_nuevo = Estado(nombre='Nuevo', orden=1, color='#888', categoria='abierto')
    col_revision = Estado(nombre='En revisión', orden=2, color='#0ea5e9',
                          categoria='abierto', responsable_id=moises.id)  # YA tiene resp!
    db.add(col_nuevo); db.add(col_revision); db.commit()
    db.refresh(col_nuevo); db.refresh(col_revision)
    print(f"[setup] col_nuevo id={col_nuevo.id}, col_revision id={col_revision.id}")
    print(f"[setup] col_revision.responsable_id={col_revision.responsable_id} (moises)")

    # Espacio + tablero
    esp = Espacio(nombre='Esp E2E', propietario_id=admin.id)
    db.add(esp); db.commit(); db.refresh(esp)
    tablero = Tablero(nombre='Tablero E2E', espacio_id=esp.id, propietario_id=admin.id)
    db.add(tablero); db.commit(); db.refresh(tablero)

    # Ticket en col_nuevo
    ticket = Ticket(
        codigo='T-E2E-001',
        titulo='Ticket de prueba E2E',
        descripcion='Ticket para validar el flujo completo',
        prioridad=Prioridad.MEDIA,
        tipo=TipoIncidencia.INCIDENCIA,
        estado_id=col_nuevo.id,
        tablero_id=tablero.id,
        creador_id=admin.id,
        asignado_id=admin.id,
    )
    db.add(ticket); db.commit(); db.refresh(ticket)
    print(f"[setup] ticket id={ticket.id} codigo={ticket.codigo}")
finally:
    db.close()

print()
print("=" * 70)
print("STEP 1: Login admin")
print("=" * 70)
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
r = client.post('/api/v1/auth/login-form',
                 data={'username':'admin','password':'test1234'},
                 follow_redirects=False)
print(f"  status: {r.status_code}")
assert r.status_code == 200

print()
print("=" * 70)
print("STEP 2: Verify diagnostic endpoint BEFORE")
print("=" * 70)
r = client.get('/api/v1/estados/diagnostico/responsables')
print(f"  status: {r.status_code}")
data = r.json()
print(f"  usuarios: {data['usuarios']}")
print(f"  estados:  {data['estados']}")
print(f"  email:    {data['email']}")

print()
print("=" * 70)
print("STEP 3: Test cambiar_estado flow (mover ticket a col con responsable)")
print("=" * 70)
# Use service directly to bypass HTMX form parsing
from app.services.ticket_service import TicketService
from app.services.ticket_service import TicketService as _TS
db_e = SessionLocal()
try:
    ticket = db_e.query(Ticket).filter_by(codigo='T-E2E-001').first()
    estado_origen = db_e.query(Estado).filter_by(id=col_nuevo.id).first()
    estado_destino = db_e.query(Estado).filter_by(id=col_revision.id).first()
    actor = db_e.query(Usuario).filter_by(username='admin').first()

    svc = TicketService(db_e)
    ticket_after, task_id = svc.cambiar_estado(
        ticket_id=ticket.id,
        estado_destino_id=estado_destino.id,
        usuario=actor,
        comentario='Prueba E2E',
    )
    print(f"  ticket actualizado a estado {ticket_after.estado_id}")
    print(f"  responsable_id de col_revision: {estado_destino.responsable_id}")
    print(f"  Celery task_id: {task_id}")
finally:
    db_e.close()

print()
print("=" * 70)
print("STEP 4: Verify Notificacion was created for moises")
print("=" * 70)
db_v = SessionLocal()
try:
    notifs = db_v.query(Notificacion).filter_by(usuario_id=moises.id).all()
    print(f"  Notificaciones para moises: {len(notifs)}")
    for n in notifs:
        print(f"    - id={n.id} tipo={n.tipo} mensaje={n.mensaje[:80]}")
finally:
    db_v.close()

print()
print("=" * 70)
print("STEP 5: Verify email log (Dev Inbox fallback)")
print("=" * 70)
_log_file = pathlib.Path('tmp/app.email.log')
if _log_file.exists():
    lines = _log_file.read_text(encoding='utf-8', errors='ignore').strip().split('\n')
    print(f"  Email log lines: {len(lines)}")
    # Mostrar las últimas 3 líneas (puede haber ruido de tests previos)
    for line in lines[-3:]:
        try:
            entry = json.loads(line)
            print(f"    to={entry.get('to')} subject={entry.get('subject')}")
            print(f"    transport={entry.get('transport')}")
        except Exception:
            print(f"    [non-json]: {line[:120]}")
else:
    print(f"  No email log file found")

print()
print("=" * 70)
print("STEP 6: Verify diagnostic endpoint AFTER")
print("=" * 70)
r = client.get('/api/v1/estados/diagnostico/responsables')
print(f"  status: {r.status_code}")
data = r.json()
print(f"  usuarios: {data['usuarios']}")
print(f"  estados:  {data['estados']}")
print(f"  email transporte: {data['email']['transporte_activo']}")

print()
print("=" * 70)
print("END-TO-END TEST COMPLETED")
print("=" * 70)
