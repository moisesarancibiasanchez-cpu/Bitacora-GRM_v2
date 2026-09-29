"""
Validacion exhaustiva de la API REST.

1. Carga la app FastAPI real y enumera todas las rutas registradas
   (recursando en sub-routers / _IncludedRouter).
2. Verifica que cada endpoint protegido tenga dependencia de autenticacion.
3. Cross-check: para cada URL usada en templates (hx-get/post/delete, href)
   existe una ruta que la pueda servir.
"""
import os
import re
import sys
from collections import defaultdict
from fastapi.routing import APIRoute, APIRouter


def _iter_router_entries(router):
    """Itera todas las rutas de un APIRouter, incluyendo _IncludedRouter anidados."""
    for r in getattr(router, "routes", []):
        tname = type(r).__name__
        if tname == "_IncludedRouter":
            orig = getattr(r, "original_router", None)
            if orig is not None:
                yield from _iter_router_entries(orig)
        else:
            yield r


def collect_routes(app_or_router, prefix=""):
    """Recorre routers y devuelve una lista de (method, path, route_obj)."""
    out = []
    for r in _iter_router_entries(app_or_router):
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", set()) or set()
        if not path or not methods:
            continue
        for m in methods:
            if m == "HEAD":
                continue
            out.append((m, prefix + path, r))
    return out


PUBLIC_PATTERNS = [
    r"^/auth/login",
    r"^/auth/registro",
    r"^/auth/recuperar",
    r"^/$",
    r"^/static/",
    r"^/health",
    r"^/docs",
    r"^/openapi",
    r"^/redoc",
    r"^/favicon",
    r"^/login$",
    r"^/logout$",
    r"^/registro$",
    r"^/tableros/publico",
    r"^/_diag/",
    r"^/_",
    r"^/p/",
]


def is_public(path: str) -> bool:
    return any(re.search(p, path) for p in PUBLIC_PATTERNS)


def has_auth_dep(route) -> bool:
    """Detecta si una ruta depende de get_current_user/require_role/require_admin."""
    dependant = getattr(route, "dependant", None)
    if not dependant:
        return False
    seen = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        call_name = getattr(d.call, "__name__", "") or ""
        qual = getattr(d.call, "__qualname__", "") or ""
        # Detectar dependencias "manuales" via wrapper _require_session_or_redirect
        # inspeccionando el codigo fuente del callable.
        try:
            import inspect
            src = inspect.getsource(d.call)
        except (OSError, TypeError):
            src = ""
        for needle in (
            "get_current_user",
            "require_role",
            "require_admin",
            "_require_session_or_redirect",
            "_get_usuario_actual",
            "verify_jwt",
        ):
            if needle in call_name or needle in qual or needle in src:
                return True
        for sub in getattr(d, "dependencies", []) or []:
            stack.append(sub)
    return False


def main():
    os.environ.setdefault("DATABASE_URL", "sqlite:///./_validate_api.db")
    os.environ.setdefault("SECRET_KEY", "validate-only-secret-key-12345678901234567890")
    os.environ.setdefault("ALLOW_XUSER_HEADER", "false")

    from app.main import app

    # Recoger TODAS las rutas recursando en routers anidados
    routes = collect_routes(app, prefix="/api/v1")
    # Sumar las page routes (las que están registradas en app directamente con prefix "")
    page_routes = []
    for r in app.routes:
        if hasattr(r, "router"):
            continue
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", set()) or set()
        if not path or not methods:
            continue
        if path.startswith("/api/") or path.startswith("/static") or path.startswith("/onboarding"):
            continue
        for m in methods:
            if m == "HEAD":
                continue
            page_routes.append((m, path, r))

    routes.extend(page_routes)
    print(f"Total de rutas registradas (recursivo): {len(routes)}")

    idx = defaultdict(list)
    for method, path, route in routes:
        norm = re.sub(r"\{[^}]+\}", "{}", path)
        idx[(method, norm)].append(path)

    no_auth = []
    for method, path, route in routes:
        if is_public(path):
            continue
        if not has_auth_dep(route):
            no_auth.append(f"{method:6s} {path}")

    print(f"Rutas SIN auth explicita: {len(no_auth)}")
    if no_auth:
        for x in no_auth[:50]:
            print(f"   - {x}")

    template_urls = set()
    for root, _dirs, files in os.walk("app/templates"):
        for f in files:
            if not f.endswith((".html", ".py")):
                continue
            src = open(os.path.join(root, f)).read()
            for m in re.finditer(r'hx-(get|post|put|delete|patch)="([^"]+)"', src):
                url = m.group(2)
                if not url.startswith("/") or "{" in url:
                    continue
                template_urls.add((m.group(1).upper(), url.split("?")[0]))

    matched = []
    unmatched = []
    for method, url in sorted(template_urls):
        if (method, url) in idx:
            matched.append((method, url))
            continue
        if (method, re.sub(r"\{[^}]+\}", "{}", url)) in idx:
            matched.append((method, url))
            continue
        unmatched.append((method, url))

    print()
    print(f"URLs en templates: {len(template_urls)}")
    print(f"  Coinciden con rutas registradas: {len(matched)}")
    print(f"  NO coinciden (posibles links rotos): {len(unmatched)}")
    for method, url in unmatched[:40]:
        print(f"   - {method:6s} {url}")

    return 1 if unmatched else 0


if __name__ == "__main__":
    sys.exit(main())
