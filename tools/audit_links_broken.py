"""Audit broken links - normaliza {{ }} y verifica contra rutas declaradas."""
import os
import re
from collections import Counter

api_set = set()
for root, _, files in os.walk('app/api'):
    for f in files:
        if f.endswith('.py'):
            p = os.path.join(root, f)
            content = open(p).read()
            for m in re.finditer(
                r'@router\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
                content,
            ):
                api_set.add('/api/v1' + m.group(1))

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
        if f.endswith('.html'):
            p = os.path.join(root, f)
            content = open(p).read()
            for m in re.finditer(r'hx-(?:get|post|patch|put|delete)\s*=\s*["\']([^"\']+)["\']', content):
                refs.append((p, normalize(m.group(1))))
            for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', content):
                h = m.group(1)
                if not h.startswith(('http', 'mailto', 'tel', '#', 'javascript:', '/static/', '/onboarding/', '/docs/')):
                    refs.append((p, normalize(h)))

static_total = sum(1 for _, r in refs if '{}' not in r and '{' not in r)
print(f'Refs con path estático: {static_total}')

broken = []
for p, ref in refs:
    if ref in declared_norm:
        continue
    if '{}' in ref or '{' in ref:
        continue
    broken.append((p, ref))

print(f'Refs rotas detectadas: {len(broken)}')
print()
print('=== Detalle ===')
for p, ref in sorted(set(broken)):
    print(f' {p}: {ref}')
