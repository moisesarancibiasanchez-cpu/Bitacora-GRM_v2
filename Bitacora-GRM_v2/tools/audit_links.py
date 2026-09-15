"""Audit - Cross-check template references against declared routes."""
import os
import re
from collections import Counter

# 1) Recolectar rutas declaradas (api/main)
api_patterns = []
api_set = set()
for root, _, files in os.walk('app/api'):
    for f in files:
        if f.endswith('.py'):
            p = os.path.join(root, f)
            for m in re.finditer(
                r'@router\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
                open(p).read(),
            ):
                api_set.add('/api/v1' + m.group(1))

main_set = set()
for m in re.finditer(
    r'@app\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
    open('app/main.py').read(),
):
    main_set.add(m.group(1))

all_routes = api_set | main_set

# 2) Buscar referencias en plantillas
refs = []
for root, _, files in os.walk('app/templates'):
    for f in files:
        if f.endswith('.html'):
            p = os.path.join(root, f)
            content = open(p).read()
            # hx-get / hx-post / hx-patch / hx-delete / hx-put
            for m in re.finditer(r'hx-(?:get|post|patch|put|delete)\s*=\s*["\']([^"\']+)["\']', content):
                refs.append((p, 'HX', m.group(1)))
            # href
            for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', content):
                href = m.group(1)
                if not href.startswith(('http', 'mailto', 'tel', '#', 'javascript:')) and href.startswith('/'):
                    refs.append((p, 'HREF', href))
            # url_for
            for m in re.finditer(r'url_for\(\s*["\']([^"\']+)["\']', content):
                refs.append((p, 'URLFOR', m.group(1)))

# 3) Detectar refs rotas
hints = Counter()
broken = []
seen = Counter()
for p, kind, ref in refs:
    seen[ref] += 1

print(f'Total referencias en plantillas: {len(refs)}')
print(f'Total únicas: {len(seen)}')
print(f'Rutas declaradas:               {len(all_routes)}')
print()
print('=== Top 40 referencias más usadas ===')
for ref, n in seen.most_common(40):
    print(f'  {n:3d}  {ref}')
