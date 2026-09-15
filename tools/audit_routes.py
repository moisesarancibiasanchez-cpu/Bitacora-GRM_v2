"""Audit - Recolecta rutas declaradas y muestra inventario."""
import re
import os

routes_api = set()
for root, _, files in os.walk('app/api'):
    for f in files:
        if f.endswith('.py'):
            p = os.path.join(root, f)
            content = open(p).read()
            for m in re.finditer(
                r'@router\.(?:get|post|patch|put|delete|head|options)\(\s*["\']([^"\']+)["\']',
                content,
            ):
                routes_api.add(m.group(1))

content = open('app/main.py').read()
routes_main = set()
for m in re.finditer(
    r'@app\.(?:get|post|patch|put|delete|head|options)\(\s*["\']([^"\']+)["\']',
    content,
):
    routes_main.add(m.group(1))

print(f'Rutas en routers api (con prefijo /api/v1): {len(routes_api)}')
print(f'Rutas en app main:                          {len(routes_main)}')
print()
print('=== Rutas main (páginas) ===')
for r in sorted(routes_main):
    print(' MAIN', r)
print()
print('=== Rutas API (con prefijo /api/v1) - sample ===')
for r in sorted(routes_api)[:40]:
    print(' ', r)
