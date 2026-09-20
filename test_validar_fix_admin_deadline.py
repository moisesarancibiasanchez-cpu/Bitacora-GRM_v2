#!/usr/bin/env python3
"""Validates the fix for /admin/deadline/ejecutar endpoint.

This test verifies:
1. The route exists and returns 200 for admin user.
2. The route returns JSONResponse with the correct field names
   (tickets_encontrados, notificaciones_creadas, emails_enviados).
3. The route does NOT raise TypeError (the previous bug).
"""
import os
import sys
import tempfile

# Use a file-based SQLite DB so tables persist for the test client
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret-validar-fix'
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
        db.add(admin)
        db.commit()
        print('admin created')
finally:
    db.close()

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Login
r = client.post('/api/v1/auth/login-form',
                data={'username': 'admin', 'password': 'test1234'},
                follow_redirects=False)
print(f'login status: {r.status_code}')

# Test 1: GET /admin/deadline should return 200
r = client.get('/admin/deadline', follow_redirects=True)
print(f'GET /admin/deadline: status={r.status_code} len={len(r.text)}')
assert r.status_code == 200, f"Expected 200, got {r.status_code}"

# Test 2: POST /admin/deadline/ejecutar with trigger=todos should not raise TypeError
print('\n--- Testing trigger=todos ---')
r = client.post('/admin/deadline/ejecutar', data={'trigger': 'todos'})
print(f'POST trigger=todos: status={r.status_code}')
data = r.json()
print(f'Response keys: {list(data.keys())}')
assert data.get('ok'), f"Expected ok=True, got: {data}"
assert 'resultados' in data, f"Expected 'resultados' key, got: {data.keys()}"
resultados = data['resultados']
# `ejecutar_todos_los_triggers` returns a dict keyed by trigger name
expected_keys = {'deadline_today', 'deadline_missed', 'deadline_approaching', 'task_overdue'}
actual_keys = set(resultados.keys())
print(f'TODOS result keys: {sorted(actual_keys)}')
assert expected_keys.issubset(actual_keys), (
    f"Missing keys: {expected_keys - actual_keys}. Got: {actual_keys}"
)

# Validate field names on the first trigger result
first_key = list(resultados.keys())[0]
todos_result = resultados[first_key]
# These are the CORRECT field names after the fix
expected_fields = {'trigger', 'tickets_encontrados', 'notificaciones_creadas',
                   'emails_enviados', 'tickets', 'errores'}
actual_fields = set(todos_result.keys())
print(f'{first_key} result fields: {sorted(actual_fields)}')
assert expected_fields.issubset(actual_fields), (
    f"Missing fields: {expected_fields - actual_fields}. "
    f"This is the BUG if you see 'total' or 'notificados' (old wrong names)."
)
# Make sure old wrong field names are NOT present
assert 'total' not in actual_fields, "Old field 'total' should not exist (was the bug)"
assert 'notificados' not in actual_fields, "Old field 'notificados' should not exist (was the bug)"

# Test 3: All individual triggers should work without TypeError
for trig in ('today', 'missed', 'approaching', 'overdue'):
    print(f'\n--- Testing trigger={trig} ---')
    r = client.post('/admin/deadline/ejecutar', data={'trigger': trig})
    print(f'POST trigger={trig}: status={r.status_code}')
    data = r.json()
    assert data.get('ok'), f"Expected ok=True, got: {data}"
    assert trig in data['resultados'], f"Expected '{trig}' in resultados"
    res = data['resultados'][trig]
    assert expected_fields.issubset(set(res.keys())), (
        f"Missing fields for {trig}: {expected_fields - set(res.keys())}"
    )

print('\n=== ALL TESTS PASSED ===')
print('The /admin/deadline/ejecutar endpoint correctly:')
print('  - Returns JSON with ok=True')
print('  - Uses the correct field names from ResultadoTrigger')
print('  - Does not raise TypeError (uses SessionLocal correctly)')
print('  - Supports all 4 triggers + todos')
