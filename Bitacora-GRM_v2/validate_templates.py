"""
Validacion exhaustiva de templates Jinja2.

1. Compilacion de cada .html/.py (sintaxis Jinja2).
2. Verificacion de que cada hx-target="#xxx" apunte a un id declarado
   en el mismo template (o a un id del layout base).
3. Verificacion de URLs (hx-get/hx-post/hx-delete/hx-put y href).
"""
import os
import re
import sys
from jinja2 import Environment, TemplateSyntaxError


BASE_IDS = {
    # Ids provistos por base.html / app.js que cualquier template puede targetear
    "modal-root",
    "modal-container",
    "main",
    "content",
    "app",
    "notification-root",
    "toast-root",
    "flash-message",
    "page-content",
}


env = Environment()
env.filters.setdefault("safe", lambda x: x)


problems = []
ok_count = 0


def scan_template(path):
    global ok_count
    try:
        src = open(path).read()
        env.parse(src)
    except TemplateSyntaxError as e:
        problems.append(("SYNTAX", path, f"linea {e.lineno}: {e.message}"))
        return
    except Exception as e:
        problems.append(("PARSE", path, str(e)))
        return

    # Extraer todos los IDs declarados
    declared_ids = set(re.findall(r'\bid="([^"]+)"', src))
    declared_ids.update(BASE_IDS)

    # 1) hx-target="#xxx" debe apuntar a un id declarado
    for m in re.finditer(r'hx-target="#([^"]+)"', src):
        tid = m.group(1)
        if tid not in declared_ids:
            problems.append(
                ("HX-TARGET", path,
                 f'hx-target="#{tid}" apunta a un id no declarado en este template'),
            )

    # 2) hx-get/hx-post/hx-delete/hx-put: capturar URL
    for m in re.finditer(r'hx-(get|post|put|delete|patch)="([^"]+)"', src):
        verb, url = m.group(1), m.group(2)
        if url.startswith("#"):
            # OK: apunta a un id propio
            continue
        if not url.startswith("/"):
            problems.append(
                ("HX-URL", path,
                 f'hx-{verb}="{url}" no es ruta absoluta'),
            )
            continue
        # Validar llaves Jinja2 balanceadas
        if "{" in url:
            opens = url.count("{")
            closes = url.count("}")
            if opens != closes:
                problems.append(
                    ("HX-URL", path,
                     f'hx-{verb}="{url}" tiene llaves desbalanceadas'),
                )

    # 3) href="/xxx" validar formato
    for m in re.finditer(r'\bhref="(/[^"]*)"', src):
        url = m.group(1)
        if "{" in url:
            opens = url.count("{")
            closes = url.count("}")
            if opens != closes:
                problems.append(
                    ("HREF", path,
                     f'href="{url}" tiene llaves desbalanceadas'),
                )

    ok_count += 1


count = 0
for root, _dirs, files in os.walk("app/templates"):
    for f in files:
        if f.endswith((".html", ".py")):
            scan_template(os.path.join(root, f))
            count += 1


print(f"Templates escaneados: {count}")
print(f"Templates OK: {ok_count}")
print(f"Problemas detectados: {len(problems)}")
print("=" * 80)
for kind, path, msg in problems[:80]:
    print(f"  [{kind}] {path}")
    print(f"      {msg}")
if len(problems) > 80:
    print(f"  ... y {len(problems) - 80} problemas mas")
sys.exit(1 if problems else 0)
