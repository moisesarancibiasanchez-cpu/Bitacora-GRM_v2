"""Audit broken links - respeta prefijos per-router."""
import os
import re
from collections import defaultdict

GLOBAL_PREFIX = '/api/v1'

# Recolectar prefijos por archivo router
router_prefix = {}
api_routes_by_file = defaultdict(set)

for root, _, files in os.walk('app/api'):
    for f in files:
        if not f.endswith('.py'):
            continue
        p = os.path.join(root, f)
        content = open(p).read()

        # prefijos del archivo
        prefixes = []
        for m in re.finditer(r'APIRouter\(\s*prefix\s*=\s*["\']([^"\']+)["\']', content):
            prefixes.append(m.group(1))
        router_prefix[p] = ''.join(prefixes) if prefixes else ''

        for m in re.finditer(r'@router\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']', content):
            api_routes_by_file[p].add(m.group(1))

api_set = set()
for p, routes in api_routes_by_file.items():
    pre = router_prefix[p]
    for r in routes:
        api_set.add(GLOBAL_PREFIX + pre + r)

main_set = set()
for m in re.finditer(
    r'@app\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
    open('app/main.py').read(),
):
    main_set.add(m.group(1))

declared = api_set | main_set

def normalize(u):
    u = u.split('?')[0]
    u = re.sub(r'\{\{[^}]+\}\}', '{}', u)
    return u

declared_norm = set(normalize(d) for d in declared)

refs = []
for root, _, files in os.walk('app/templates'):
    for f in files:
        if not f.endswith('.html'):
            continue
        p = os.path.join(root, f)
        content = open(p).read()
        for m in re.finditer(r'hx-(?:get|post|patch|put|delete)\s*=\s*["\']([^"\']+)["\']', content):
            refs.append((p, normalize(m.group(1))))
        for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', content):
            h = m.group(1)
            if not h.startswith(('http', 'mailto', 'tel', '#', 'javascript:', '/static/', '/onboarding/', '/docs/')):
                refs.append((p, normalize(h)))

broken = []
seen_refs = set()
for p, ref in refs:
    if ref in seen_refs:
        continue
    seen_refs.add(ref)
    if ref in declared_norm:
        continue
    if '{}' in ref or '{' in ref:
        continue
    broken.append((p, ref))

print(f'Total refs únicas: {len(seen_refs)}')
print(f'Refs rotas (estáticas que NO matchean): {len(broken)}')
print()
print('=== Detalle de refs rotas ===')
for p, ref in sorted(set(broken)):
    print(f' {p}: {ref}')

print()
print('=== Cobertura de refs estáticas ===')
total_static = sum(1 for r in seen_refs if '{}' not in r and '{' not in r)
matched = sum(1 for r in seen_refs if r in declared_norm and '{}' not in r and '{' not in r)
print(f' Estáticas totales: {total_static}')
print(f' Matchean ruta declarada: {matched}')
print(f' Cobertura: {matched / total_static * 100 if total_static else 0:.1f}%')
