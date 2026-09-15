#!/usr/bin/env python3
"""Trigger routes to see TemplateResponse deprecation warnings and calendar detail issue."""
import os, sys, re, tempfile

# Use a file-based SQLite DB so tables persist for the test client
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['ALLOW_XUSER_HEADER'] = 'true'

# Initialize DB BEFORE importing app
from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

# Create admin user
from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.core.security import hash_password

db = SessionLocal()
try:
    if not db.query(Usuario).filter_by(username='admin').first():
        admin = Usuario(
            username='admin', email='admin@test.com',
            nombre_completo='Admin Test', rol=RolUsuario.ADMINISTRADOR,
            hashed_password=hash_password('test1234'),
            is_active=True,
        )
        db.add(admin); db.commit()
        print('admin created')
finally:
    db.close()

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form', data={'username':'admin','password':'test1234'}, follow_redirects=False)
print('login status:', r.status_code)

# Capture all deprecation warnings
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')

    # Now hit routes that use TemplateResponse
    paths = ['/vistas/calendario', '/vistas/timeline', '/vistas/tabla', '/vistas/panel',
             '/tickets', '/kanban', '/dashboard', '/usuarios',
             '/catalogos', '/tableros', '/espacios', '/butler',
             '/importar-exportar', '/roles-funciones', '/notificaciones',
             '/auth/login', '/auth/registro']
    for path in paths:
        r = client.get(path, follow_redirects=True)
        print(f'GET {path:30s}: status={r.status_code} len={len(r.text)}')

warnings_text = '\n'.join([str(x.message) for x in w])
tr_count = warnings_text.count('TemplateResponse')
print(f'\nTemplateResponse deprecation warnings: {tr_count}')

# Show unique warnings
seen = set()
for x in w:
    msg = str(x.message)
    if 'TemplateResponse' in msg and msg[:80] not in seen:
        seen.add(msg[:80])
        print('---')
        print(msg[:600])
