"""
Smoke test: verifica que los nuevos endpoints /auth/login-form y
/auth/registro-form aceptan application/x-www-form-urlencoded y devuelven
HX-Redirect (en éxito) o un fragmento HTML con error (en fallo).

Confirma además que el bug original (form contra endpoint JSON) sigue
fallando, demostrando que la corrección es necesaria.
"""
import os
import sys
import json
import sqlite3
import tempfile

# Aislar la BD para no tocar la real
TEST_DB = tempfile.mktemp(prefix="test_auth_form_", suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-testing"

from fastapi.testclient import TestClient

# Inicializar BD mínima (tablas + 1 usuario admin) sin sembrar catálogos
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.core.security import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()
admin = Usuario(
    username="admin",
    email="admin@test.local",
    nombre_completo="Admin Test",
    hashed_password=hash_password("admin123"),
    rol=RolUsuario.ADMINISTRADOR,
    is_active=True,
)
db.add(admin)
db.commit()
db.close()

from app.main import app  # noqa: E402

client = TestClient(app)

results = []
def check(name, ok, detail=""):
    mark = "OK " if ok else "FAIL"
    results.append((ok, name, detail))
    print(f"[{mark}] {name} :: {detail}")


# --------------------------------------------------------------------
# 1) BUG ORIGINAL: HTML form contra endpoint JSON -> 422
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login",
    data={"username": "admin", "password": "admin123"},
)
check(
    "Bug original confirmado: form contra /login (JSON) -> 422",
    r.status_code == 422,
    f"status={r.status_code} (esperado 422)",
)

# --------------------------------------------------------------------
# 2) FIX: /login-form con form-urlencoded -> 200 + HX-Redirect + cookie
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "admin", "password": "admin123"},
    follow_redirects=False,
)
check(
    "Login OK devuelve HX-Redirect",
    r.status_code == 200 and r.headers.get("HX-Redirect") == "/kanban",
    f"status={r.status_code} hx-redirect={r.headers.get('HX-Redirect')!r}",
)
check(
    "Login OK setea cookie access_token",
    "access_token" in r.cookies,
    f"cookies={list(r.cookies.keys())}",
)

# --------------------------------------------------------------------
# 3) FIX: /login-form con password incorrecta -> 400 + HTML
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "admin", "password": "WRONG"},
)
check(
    "Login con password incorrecta -> 400 + HTML",
    r.status_code == 400 and "<div" in r.text and "Credenciales inválidas" in r.text,
    f"status={r.status_code} body[:80]={r.text[:80]!r}",
)

# --------------------------------------------------------------------
# 4) FIX: /login-form con usuario inexistente -> 400 + HTML
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "noexiste", "password": "x"},
)
check(
    "Login con usuario inexistente -> 400 + HTML",
    r.status_code == 400 and "Credenciales inválidas" in r.text,
    f"status={r.status_code}",
)

# --------------------------------------------------------------------
# 5) FIX: /login-form con campos vacíos -> 400 + HTML
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "", "password": ""},
)
check(
    "Login con campos vacíos -> 400 + HTML",
    r.status_code == 400 and "obligatorios" in r.text,
    f"status={r.status_code} body[:120]={r.text[:120]!r}",
)

# --------------------------------------------------------------------
# 6) FIX: /login-form con email en vez de username -> funciona
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "admin@test.local", "password": "admin123"},
)
check(
    "Login con email funciona",
    r.status_code == 200 and r.headers.get("HX-Redirect") == "/kanban",
    f"status={r.status_code} hx-redirect={r.headers.get('HX-Redirect')!r}",
)

# --------------------------------------------------------------------
# 7) FIX: /registro-form crea nuevo usuario y auto-login
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/registro-form",
    data={
        "nombre_completo": "Test Nuevo Usuario",
        "username": "nuevo_user",
        "email": "nuevo@test.local",
        "password": "secreto123",
        "confirm_password": "secreto123",
        "departamento": "QA",
    },
    follow_redirects=False,
)
check(
    "Registro nuevo usuario -> 200 + HX-Redirect + cookie",
    r.status_code == 200 and r.headers.get("HX-Redirect") == "/kanban"
    and "access_token" in r.cookies,
    f"status={r.status_code} hx-redirect={r.headers.get('HX-Redirect')!r}",
)

# Verificar que realmente está en BD
db = SessionLocal()
u = db.query(Usuario).filter(Usuario.username == "nuevo_user").first()
check(
    "Usuario nuevo persistido en BD con rol SOLICITANTE",
    u is not None and u.rol == RolUsuario.SOLICITANTE,
    f"encontrado={u is not None} rol={u.rol if u else None}",
)
db.close()

# --------------------------------------------------------------------
# 8) FIX: /registro-form con password mismatch -> 400 + HTML
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/registro-form",
    data={
        "nombre_completo": "Otro Usuario",
        "username": "otro_user",
        "email": "otro@test.local",
        "password": "secreto123",
        "confirm_password": "OTRA_COSA",
    },
)
check(
    "Registro con contraseñas distintas -> 400 + HTML",
    r.status_code == 400 and "no coinciden" in r.text,
    f"status={r.status_code} body[:120]={r.text[:120]!r}",
)

# --------------------------------------------------------------------
# 9) FIX: /registro-form con username duplicado -> 400 + HTML
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/registro-form",
    data={
        "nombre_completo": "Duplicado",
        "username": "admin",  # ya existe
        "email": "duplicado@test.local",
        "password": "secreto123",
        "confirm_password": "secreto123",
    },
)
check(
    "Registro con username duplicado -> 400 + HTML",
    r.status_code == 400 and "ya está registrado" in r.text,
    f"status={r.status_code} body[:120]={r.text[:120]!r}",
)

# --------------------------------------------------------------------
# 10) FIX: /registro-form con username con caracteres inválidos
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/registro-form",
    data={
        "nombre_completo": "Caracteres Raros",
        "username": "u!@#",
        "email": "raro@test.local",
        "password": "secreto123",
        "confirm_password": "secreto123",
    },
)
check(
    "Registro con username inválido -> 400 + HTML",
    r.status_code == 400 and "usuario" in r.text.lower(),
    f"status={r.status_code} body[:120]={r.text[:120]!r}",
)

# --------------------------------------------------------------------
# 11) FIX: /registro-form con email malformado
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/registro-form",
    data={
        "nombre_completo": "Email Raro",
        "username": "emilraro",
        "email": "no-es-email",
        "password": "secreto123",
        "confirm_password": "secreto123",
    },
)
check(
    "Registro con email inválido -> 400 + HTML",
    r.status_code == 400 and "email" in r.text.lower(),
    f"status={r.status_code} body[:120]={r.text[:120]!r}",
)

# --------------------------------------------------------------------
# 12) Sanity: GET /auth/check con la cookie de admin funciona
# --------------------------------------------------------------------
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "admin", "password": "admin123"},
)
cookies = r.cookies
r = client.get("/api/v1/auth/check", cookies=cookies)
check(
    "GET /auth/check con cookie válida -> 200 + authenticated",
    r.status_code == 200 and r.json().get("authenticated") is True
    and r.json().get("username") == "admin",
    f"status={r.status_code} body={r.json()}",
)

# --------------------------------------------------------------------
# Resumen
# --------------------------------------------------------------------
passed = sum(1 for ok, *_ in results if ok)
total = len(results)
print()
print("=" * 60)
print(f"Tests pasados: {passed}/{total}")
print("=" * 60)

# Limpieza
try:
    os.unlink(TEST_DB)
except Exception:
    pass

sys.exit(0 if passed == total else 1)
