#!/usr/bin/env python3
"""Test the responsable picker + notification flow to find the breakage."""
import os, sys, tempfile, logging
logging.disable(logging.CRITICAL)
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
    # === SETUP: admin user + several regular users ===
    admin = Usuario(username='admin', email='admin@test.com',
                    nombre_completo='Administrador Sistema',
                    rol=RolUsuario.ADMINISTRADOR,
                    hashed_password=hash_password('test1234'),
                    is_active=True)
    db.add(admin); db.commit(); db.refresh(admin)
    print(f"[setup] admin id={admin.id}")

    # Active users (should appear in picker)
    users_to_create = [
        ('moises',  'moises@test.com',  'Moisés Arancibia Sánchez',  RolUsuario.AGENTE_SENIOR),
        ('ana',     'ana@test.com',      'Ana Pérez',                  RolUsuario.AGENTE),
        ('carlos',  'carlos@test.com',   "Carlos O'Brien López",       RolUsuario.AGENTE),
        ('maria',   'maria@test.com',    'María José Rodríguez',       RolUsuario.SOLICITANTE),
    ]
    user_ids = {}
    for uname, email, fullname, rol in users_to_create:
        if not db.query(Usuario).filter_by(username=uname).first():
            u = Usuario(username=uname, email=email, nombre_completo=fullname,
                        rol=rol, hashed_password=hash_password('x'),
                        is_active=True)
            db.add(u); db.commit(); db.refresh(u)
            user_ids[uname] = u.id
            print(f"[setup] active user: {uname} id={u.id}")

    # Inactive user (should NOT appear in picker)
    if not db.query(Usuario).filter_by(username='inactivo').first():
        u = Usuario(username='inactivo', email='inactivo@test.com',
                    nombre_completo='Usuario Inactivo',
                    rol=RolUsuario.AGENTE,
                    hashed_password=hash_password('x'),
                    is_active=False)
        db.add(u); db.commit()
        print(f"[setup] INACTIVE user created (should be hidden from picker)")

    # === Setup: column (estado) ===
    estado = Estado(nombre='En revisión', orden=1, color='#0ea5e9',
                    categoria='abierto', responsable_id=None)
    db.add(estado); db.commit(); db.refresh(estado)
    print(f"[setup] estado id={estado.id} nombre='{estado.nombre}'")
finally:
    db.close()

# === TEST 1: Login as admin via TestClient ===
print()
print("=" * 70)
print("TEST 1: Login admin")
print("=" * 70)
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form',
                 data={'username':'admin','password':'test1234'},
                 follow_redirects=False)
print(f"  login status: {r.status_code}")

# === TEST 2: GET picker for estado ===
print()
print("=" * 70)
print("TEST 2: GET responsable-picker for estado", estado.id)
print("=" * 70)
r = client.get(f'/api/v1/estados/{estado.id}/responsable-picker',
               follow_redirects=True)
print(f"  status={r.status_code} len={len(r.text)}")
print()
print("  --- HTML returned ---")
print(r.text[:2500])
print("  --- end ---")
print()
# Count <option> entries
import re
options = re.findall(r'<option[^>]*>', r.text)
print(f"  Total <option> tags: {len(options)}")
# Show first 5 options
for o in options[:8]:
    print(f"    {o[:120]}")

# === TEST 3: PATCH responsable_id ===
print()
print("=" * 70)
print("TEST 3: PATCH responsable_id=moises via HTMX form")
print("=" * 70)
moises_id = user_ids['moises']
r = client.patch(f'/api/v1/estados/{estado.id}',
                  data={'responsable_id': str(moises_id)},
                  headers={
                      'HX-Request': 'true',
                      'Content-Type': 'application/x-www-form-urlencoded',
                  },
                  follow_redirects=True)
print(f"  status={r.status_code} len={len(r.text)}")
# Show fragment
print("  --- HTML returned (first 600 chars) ---")
print(r.text[:600])

# Verify in DB
db2 = SessionLocal()
e_after = db2.query(Estado).filter_by(id=estado.id).first()
print(f"  estado.responsable_id after PATCH: {e_after.responsable_id}")
print(f"  Expected: {moises_id}")
print(f"  Match: {e_after.responsable_id == moises_id}")
db2.close()

# === TEST 4: Trigger notificar_responsable_columna ===
print()
print("=" * 70)
print("TEST 4: notificar_responsable_columna() direct call")
print("=" * 70)
from app.services.notificacion_responsable_service import notificar_responsable_columna
db3 = SessionLocal()
try:
    # Crear ticket
    esp = Espacio(nombre='Espacio T', propietario_id=admin.id)
    db3.add(esp); db3.commit(); db3.refresh(esp)
    t1 = Tablero(nombre='T1', espacio_id=esp.id, propietario_id=admin.id)
    db3.add(t1); db3.commit(); db3.refresh(t1)
    ticket = Ticket(
        codigo='T-NTF-001',
        titulo='Ticket para probar notificación',
        descripcion='Prueba del flujo de notificación al responsable',
        prioridad=Prioridad.MEDIA,
        tipo=TipoIncidencia.INCIDENCIA,
        estado_id=estado.id,
        tablero_id=t1.id,
        creador_id=admin.id,
        asignado_id=admin.id,
    )
    db3.add(ticket); db3.commit(); db3.refresh(ticket)

    e_dest = db3.query(Estado).filter_by(id=estado.id).first()
    # Use ana as actor (different from responsable moises)
    actor = db3.query(Usuario).filter_by(username='ana').first()

    result = notificar_responsable_columna(
        db3,
        ticket=ticket,
        estado_destino=e_dest,
        estado_origen_nombre='Nuevo',
        actor=actor,
        base_url='http://localhost:3000',
    )
    db3.commit()
    print(f"  result: {result}")
finally:
    db3.close()

print()
print("=" * 70)
print("All tests completed")
print("=" * 70)
