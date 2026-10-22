#!/usr/bin/env python3
"""Test picker fallback logic by calling the function directly (bypassing auth)."""
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
from app.core.security import hash_password

db = SessionLocal()
try:
    # Setup: solo usuarios INACTIVOS (sin admin activo)
    print("[setup] Creando 3 usuarios INACTIVOS...")
    for uname in ['user1', 'user2', 'user3']:
        if not db.query(Usuario).filter_by(username=uname).first():
            u = Usuario(username=uname, email=f'{uname}@test.com',
                        nombre_completo=f'Usuario {uname}',
                        rol=RolUsuario.AGENTE,
                        hashed_password=hash_password('x'),
                        is_active=False)  # INACTIVE!
            db.add(u)
    db.commit()

    # Activar admin SOLO para poder autenticar
    admin = Usuario(username='admin', email='admin@test.com',
                    nombre_completo='Administrador Sistema',
                    rol=RolUsuario.ADMINISTRADOR,
                    hashed_password=hash_password('test1234'),
                    is_active=True)
    db.add(admin); db.commit(); db.refresh(admin)
    print(f"[setup] admin id={admin.id} (ACTIVO)")

    estado = Estado(nombre='Col Vacía', orden=1, color='#0ea5e9',
                    categoria='abierto', responsable_id=None)
    db.add(estado); db.commit(); db.refresh(estado)
    print(f"[setup] estado id={estado.id}")
finally:
    db.close()

print()
print("=" * 70)
print("TEST: Picker cuando SOLO hay usuarios inactivos (no-admin)")
print("=" * 70)

# Login
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
r = client.post('/api/v1/auth/login-form',
                 data={'username':'admin','password':'test1234'},
                 follow_redirects=False)
print(f"login status: {r.status_code}")

# Llamar al endpoint
r = client.get(f'/api/v1/estados/{estado.id}/responsable-picker',
               follow_redirects=True)
print(f"picker status: {r.status_code}")
print(f"picker length: {len(r.text)}")

import re
options = re.findall(r'<option[^>]*>([^<]*)', r.text)
print(f"\nOptions encontrados:")
for opt in options:
    print(f"  - {opt!r}")

print()
print("=" * 70)
print(f"Banner de ayuda presente: {'amber' in r.text}")
print(f"Banner contiene '/usuarios': {'/usuarios' in r.text}")
print(f"HTML completo (primeros 1500 chars):")
print(r.text[:1500])
