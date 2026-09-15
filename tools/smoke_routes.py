"""Smoke test - arranca la app y hace HEAD/GET a cada ruta pública."""
import os
import sys
import re

os.environ.setdefault('DATABASE_URL', 'sqlite:///./smoke.db')
os.environ.setdefault('SECRET_KEY', 'smoke-test-secret-key-not-for-prod')
os.environ.setdefault('DEBUG', 'false')
os.environ.setdefault('AUTO_INIT_DB', 'true')

sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Rutas a probar (sin auth donde sea posible)
endpoints_to_check = [
    ('GET',  '/health',       None),
    ('GET',  '/ready',        None),
    ('GET',  '/',             None),
    ('GET',  '/auth/login',   None),
    ('GET',  '/docs',         None),
    ('GET',  '/redoc',        None),
    ('GET',  '/kanban',       None),  # redirige a login sin sesión
    ('GET',  '/onboarding',   None),  # debe ser mount static
    ('GET',  '/onboarding/',  None),
]

results = []
for method, path, body in endpoints_to_check:
    try:
        r = client.get(path, follow_redirects=False)
        ok = r.status_code < 500
        results.append((method, path, r.status_code, ok))
    except Exception as e:
        results.append((method, path, f'EXC:{type(e).__name__}', False))

print('Smoke test de rutas públicas')
print('=' * 70)
for m, p, s, ok in results:
    flag = '✓' if ok else '✗'
    print(f'  {flag} {m:6s} {p:30s} → {s}')

failures = [r for r in results if not r[3]]
print()
print(f'Total: {len(results)} | OK: {len(results)-len(failures)} | Fail: {len(failures)}')
