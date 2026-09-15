#!/usr/bin/env python3
"""Test the responsable picker + notification flow + diagnostic endpoint (v2)."""
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

    users_to_create = [
        ('moises',  'moises@test.com',  'Moisés Arancibia',  RolUsuario.AGENTE_SENIOR),
        ('ana',     'ana@test.com',      'Ana Pérez',         RolUsuario.AGENTE),
        ('carlos',  'carlos@test.com',   "Carlos O'Brien",    RolUsuario.AGENTE),
        ('maria',   'maria@test.com',    'María José',        RolUsuario.SOLICITANTE),
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

    # Inactive user
    if not db.query(Usuario).filter_by(username='inactivo').first():
        u = Usuario(username='inactivo', email='inactivo@test.com',
                    nombre_completo='Usuario Inactivo',
                    rol=RolUsuario.AGENTE,
                    hashed_password=hash_password('x'),
                    is_active=False)
        db.add(u); db.commit()
        print(f"[setup] INACTIVE user created")

    # === Setup: column (estado) ===
    estado = Estado(nombre='En revisión', orden=1, color='#0ea5e9',
                    categoria='abierto', responsable_id=None)
    db.add(estado); db.commit(); db.refresh(estado)
    print(f"[setup] estado id={estado.id} nombre='{estado.nombre}'")
finally:
    db.close()

print()
print("=" * 70)
print("TEST A: Login admin")
print("=" * 70)
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form',
                 data={'username':'admin','password':'test1234'},
                 follow_redirects=False)
print(f"  login status: {r.status_code}")

# === TEST B: GET picker (CASO NORMAL: con usuarios activos) ===
print()
print("=" * 70)
print(f"TEST B: GET responsable-picker for estado {estado.id} (CASO NORMAL)")
print("=" * 70)
r = client.get(f'/api/v1/estados/{estado.id}/responsable-picker',
               follow_redirects=True)
print(f"  status={r.status_code} len={len(r.text)}")
import re
options = re.findall(r'<option[^>]*>', r.text)
print(f"  Total <option> tags: {len(options)}")
# Esperado: 5 (1 "Sin responsable" + admin + 4 activos; el inactivo NO aparece)
print(f"  Esperado: 5 (1 'Sin responsable' + admin + moises + ana + carlos + maria)")
print(f"  Match: {len(options) == 5}")
print(f"  HTML contiene 'inactivo': {'inactivo' in r.text.lower()}")
print(f"  HTML contiene banner amarillo: {'amber-300' in r.text}")
print()

# === TEST C: PATCH responsable_id=moises ===
print("=" * 70)
print("TEST C: PATCH responsable_id=moises via HTMX form")
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

# Verify in DB
db2 = SessionLocal()
e_after = db2.query(Estado).filter_by(id=estado.id).first()
print(f"  estado.responsable_id after PATCH: {e_after.responsable_id}")
print(f"  Expected: {moises_id}")
print(f"  Match: {e_after.responsable_id == moises_id}")
db2.close()

# === TEST D: DIAGNOSTIC endpoint ===
print()
print("=" * 70)
print("TEST D: GET /api/v1/estados/diagnostico/responsables")
print("=" * 70)
r = client.get('/api/v1/estados/diagnostico/responsables',
               follow_redirects=True)
print(f"  status={r.status_code}")
import json
try:
    data = r.json()
    print(f"  usuarios: {data.get('usuarios')}")
    print(f"  estados: {data.get('estados')}")
    print(f"  email:   {data.get('email')}")
    print(f"  solicitado_por: {data.get('solicitado_por')}")
except Exception as e:
    print(f"  ERROR parsing JSON: {e}")
    print(f"  Raw response: {r.text[:500]}")

# === TEST E: Picker cuando SOLO hay usuarios inactivos ===
print()
print("=" * 70)
print("TEST E: Picker when ONLY inactive users exist (FALLBACK)")
print("=" * 70)
db3 = SessionLocal()
try:
    # Desactivar SOLO usuarios NO-admin (admin debe seguir activo para auth)
    activos = db3.query(Usuario).filter(
        Usuario.is_active == True,  # noqa: E712
        Usuario.username != 'admin'
    ).all()
    for u in activos:
        u.is_active = False
    db3.commit()
    print(f"  [setup] Desactivados {len(activos)} usuarios NO-admin")
finally:
    db3.close()

r = client.get(f'/api/v1/estados/{estado.id}/responsable-picker',
               follow_redirects=True)
print(f"  status={r.status_code} len={len(r.text)}")
options = re.findall(r'<option[^>]*>', r.text)
print(f"  Total <option> tags: {len(options)}")
# Esperado: 5 (1 'Sin responsable' + 1 admin activo + 3 inactivos no-admin + 1 inactivo inicial = 5)
# (admin queda activo, los otros 4 no-admin desactivados, +1 inactivo original = 5 inactivos)
print(f"  Esperado: 5 (1 'Sin responsable' + 4 inactivos no-admin)")
# Como solo quedan admin activo + 4 inactivos no-admin, debería mostrar admin + 4 inactivos
print(f"  Options con '(inactivo)':")
for o in options:
    print(f"    {o[:120]}")
print(f"  Banner amarillo presente: {'amber-300' in r.text}")
print(f"  Banner con 'Activa al': {'Activa al' in r.text}")
print(f"  Banner contiene /usuarios: {'/usuarios' in r.text}")

# Reactivar usuarios
db4 = SessionLocal()
try:
    users = db4.query(Usuario).filter(Usuario.username != 'admin').all()
    for u in users:
        u.is_active = True
    db4.commit()
    print(f"  [teardown] Reactivados {db4.query(Usuario).filter(Usuario.is_active == True).count()} usuarios")
finally:
    db4.close()

# === TEST F: Diagnostic endpoint - BD vacía ===
print()
print("=" * 70)
print("TEST F: Diagnostic endpoint when DB has NO users")
print("=" * 70)
db5 = SessionLocal()
try:
    # Guardar admin primero
    admin_user = db5.query(Usuario).filter_by(username='admin').first()
    admin_id = admin_user.id
    print(f"  [setup] Usuarios antes: {db5.query(Usuario).count()}")
    # Borrar todos MENOS admin (necesitamos admin para auth)
    db5.query(Usuario).filter(Usuario.username != 'admin').delete()
    db5.commit()
    print(f"  [setup] Usuarios después: {db5.query(Usuario).count()}")
    # Verificar el diagnóstico
    db5.close()

    r = client.get('/api/v1/estados/diagnostico/responsables',
                   follow_redirects=True)
    print(f"  diagnostic status: {r.status_code}")
    import json as _json
    data = r.json()
    print(f"  usuarios.alerta: {data.get('usuarios', {}).get('alerta')}")
    print(f"  Esperado 'OK' si admin sigue activo: {data.get('usuarios', {}).get('alerta') == 'OK'}")
finally:
    pass

print()
print("=" * 70)
print("All tests completed")
print("=" * 70)
