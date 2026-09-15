#!/usr/bin/env python3
"""Test calendar detail to find the breaking issue."""
import os, sys, tempfile, logging
logging.disable(logging.CRITICAL)
# Suppress SQLAlchemy info logs
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
import warnings
warnings.filterwarnings('ignore')

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['ALLOW_XUSER_HEADER'] = 'true'

from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.espacio import Espacio, Tablero
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.core.security import hash_password
from datetime import datetime, timedelta

db = SessionLocal()
try:
    if not db.query(Usuario).filter_by(username='admin').first():
        admin = Usuario(username='admin', email='a@a.com', nombre_completo='Admin User',
                       rol=RolUsuario.ADMINISTRADOR, hashed_password=hash_password('test1234'),
                       is_active=True)
        db.add(admin); db.commit()

    estados = []
    for i, n in enumerate(['Nuevo', 'En Progreso', 'Cerrado']):
        if not db.query(Estado).filter_by(nombre=n).first():
            e = Estado(nombre=n, orden=i, color='#000')
            db.add(e); db.commit()
        estados.append(db.query(Estado).filter_by(nombre=n).first())

    esp = db.query(Espacio).filter_by(nombre='Espacio Test').first()
    if not esp:
        esp = Espacio(nombre="Espacio Test", propietario_id=admin.id)
        db.add(esp); db.commit()
    t1 = db.query(Tablero).filter_by(nombre='Tablero Test', espacio_id=esp.id).first()
    if not t1:
        t1 = Tablero(nombre='Tablero Test', espacio_id=esp.id, propietario_id=admin.id)
        db.add(t1); db.commit()

    admin = db.query(Usuario).filter_by(username='admin').first()
    if not db.query(Ticket).filter_by(codigo='T-001').first():
        ticket = Ticket(
            codigo='T-001',
            titulo='Ticket de prueba para calendario',
            descripcion='Descripcion del ticket de prueba.',
            prioridad=Prioridad.ALTA,
            tipo=TipoIncidencia.INCIDENCIA,
            estado_id=estados[0].id,
            tablero_id=t1.id,
            creador_id=admin.id,
            asignado_id=admin.id,
            fecha_inicio=datetime.utcnow() - timedelta(days=2),
            fecha_vencimiento_sla=datetime.utcnow() + timedelta(days=5),
        )
        db.add(ticket); db.commit()
        print(f'Ticket created: id={ticket.id} codigo={ticket.codigo}')
finally:
    db.close()

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form', data={'username':'admin','password':'test1234'}, follow_redirects=False)
print(f'login status: {r.status_code}')

print('\n=== TEST 1: GET /vistas/calendario ===')
r = client.get('/vistas/calendario', follow_redirects=True)
print(f'  status={r.status_code} len={len(r.text)}')
print(f'  has filtro form: {"filtros-calendario" in r.text}')
print(f'  has ticket link: {"/api/v1/tickets/1/detalle-html" in r.text}')

print('\n=== TEST 2: GET detalle-html ===')
r = client.get('/api/v1/tickets/1/detalle-html', follow_redirects=True)
print(f'  status={r.status_code} len={len(r.text)}')
print(f'  has data-modal attr: {"data-modal" in r.text}')
print(f'  has modal-backdrop class: {"modal-backdrop" in r.text}')
print(f'  has data-close-modal: {"data-close-modal" in r.text}')
print(f'  has codigo T-001: {"T-001" in r.text}')

print('\n=== TEST 3: GET detalle-html?tab=comentarios ===')
r = client.get('/api/v1/tickets/1/detalle-html?tab=comentarios', follow_redirects=True)
print(f'  status={r.status_code} len={len(r.text)}')

print('\n=== TEST 4: GET detalle-html?tab=invalid (test fallback) ===')
r = client.get('/api/v1/tickets/1/detalle-html?tab=invalid_tab', follow_redirects=True)
print(f'  status={r.status_code} len={len(r.text)}')

print('\n=== TEST 5: GET detalle-html for non-existent ticket ===')
r = client.get('/api/v1/tickets/9999/detalle-html', follow_redirects=True)
print(f'  status={r.status_code}')

# Check for render errors
text = r.text
if r.status_code == 200 and ('Error' in text[:1000] or 'undefined' in text[:1000].lower()):
    print('POSSIBLE ERROR in first 1000 chars:')
    print(text[:1000])
