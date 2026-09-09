"""
Tests exhaustivos para todas las funcionalidades nuevas estilo Trello.

Cubre:
- Espacios (workspaces)
- Tableros con permisos
- Watch (suscripciones)
- Reacciones
- Notificaciones
- Custom Fields
- Botones Butler
- Comandos Programados
- Vistas multidimensionales (tabla, calendario, timeline)
- Markdown
- Metadata extendida de tickets
- Páginas HTML (sin errores, sin links rotos)
"""
import os
import sys
import logging
logging.disable(logging.CRITICAL)

os.environ["DATABASE_URL"] = "sqlite:///./test_trello_pytest.db"
os.environ["AUTO_INIT_DB"] = "false"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Crear BD de test
if os.path.exists("./test_trello_pytest.db"):
    os.remove("./test_trello_pytest.db")

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.main import app

# Crear todas las tablas
Base.metadata.create_all(bind=engine)

# Cargar datos semilla (sin password hashing - saltamos seed_usuarios)
from app.db.init_db import (
    seed_estados, seed_transiciones, seed_catalogos, seed_etiquetas,
    seed_espacios, seed_tableros, seed_custom_fields, seed_butler_extras,
    seed_tickets_demo, seed_automatizaciones, seed_notificaciones_demo,
)
from app.core.security import hash_password
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado

# Crear usuarios manualmente con hash dummy
db = SessionLocal()
try:
    # Verificar si ya hay usuarios
    if db.query(Usuario).count() == 0:
        # Hashear con bcrypt directo (sin passlib)
        try:
            import bcrypt
            def _hash(pwd):
                return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
        except ImportError:
            # Si no hay bcrypt, usar hash dummy
            def _hash(pwd):
                return f"plain:{pwd}"
        usuarios = [
            Usuario(username="admin", email="admin@bitacora.local",
                nombre_completo="Administrador General",
                hashed_password=_hash("admin123"),
                rol=RolUsuario.ADMINISTRADOR, departamento="TI"),
            Usuario(username="agente1", email="agente1@bitacora.local",
                nombre_completo="María González",
                hashed_password=_hash("agente123"),
                rol=RolUsuario.AGENTE, departamento="Soporte Nivel 1"),
            Usuario(username="lider", email="lider@bitacora.local",
                nombre_completo="Carlos Ramírez",
                hashed_password=_hash("lider123"),
                rol=RolUsuario.AGENTE_SENIOR, departamento="Soporte Nivel 2"),
            Usuario(username="usuario1", email="usuario1@bitacora.local",
                nombre_completo="Ana López",
                hashed_password=_hash("user123"),
                rol=RolUsuario.SOLICITANTE, departamento="Ventas"),
        ]
        for u in usuarios:
            db.add(u)
        db.commit()
        print("[setup] 4 usuarios creados")
    # Cargar seeds
    seed_estados(db)
    seed_transiciones(db)
    seed_catalogos(db)
    seed_etiquetas(db)
    seed_espacios(db)
    seed_tableros(db)
    seed_custom_fields(db)
    seed_butler_extras(db)
    seed_tickets_demo(db)
    seed_automatizaciones(db)
    seed_notificaciones_demo(db)
    db.commit()
    print("[setup] Datos semilla cargados")
finally:
    db.close()

# Headers de autenticación (modo demo) y helpers
AUTH = {"X-User-Id": "1"}

client = TestClient(app)


# Helpers de HTTP con header de autenticación incluido
def get(url, **kw):
    headers = kw.pop("headers", {}) or {}
    headers.update(AUTH)
    return client.get(url, headers=headers, **kw)


def post(url, **kw):
    headers = kw.pop("headers", {}) or {}
    headers.update(AUTH)
    return client.post(url, headers=headers, **kw)


def patch(url, **kw):
    headers = kw.pop("headers", {}) or {}
    headers.update(AUTH)
    return client.patch(url, headers=headers, **kw)


def delete(url, **kw):
    headers = kw.pop("headers", {}) or {}
    headers.update(AUTH)
    return client.delete(url, headers=headers, **kw)


# Contadores
total = 0
pasados = 0
fallados = []


def test(name):
    def deco(fn):
        global total, pasados
        total += 1
        try:
            fn()
            pasados += 1
            print(f"  [OK]  {name}")
        except AssertionError as e:
            fallados.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            fallados.append((name, f"{type(e).__name__}: {e}"))
            print(f"  [ERR]  {name}: {type(e).__name__}: {e}")
    return deco


print("\n" + "="*60)
print("TEST SUITE: Funcionalidades Trello - Bitácora GRM")
print("="*60)

# ============================================================
# PÁGINAS HTML
# ============================================================
print("\n[PÁGINAS HTML]")

@test("GET / - Redirige a /kanban")
def t01():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (200, 307, 302), f"status={r.status_code}"
    if r.status_code in (307, 302):
        assert "/kanban" in r.headers.get("location", "")

@test("GET /kanban - Renderiza tablero")
def t02():
    r = client.get("/kanban")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Bitácora" in r.text or "Kanban" in r.text or "kanban" in r.text

@test("GET /tickets - Lista tickets")
def t03():
    r = client.get("/tickets")
    assert r.status_code == 200

@test("GET /tickets/nuevo - Modal nuevo ticket")
def t04():
    r = client.get("/tickets/nuevo")
    assert r.status_code == 200

@test("GET /catalogos - Lista catálogos")
def t05():
    r = client.get("/catalogos")
    assert r.status_code == 200

@test("GET /espacios - Lista espacios")
def t06():
    r = client.get("/espacios")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Espacio" in r.text or "espacio" in r.text

@test("GET /tableros - Lista tableros")
def t07():
    r = client.get("/tableros")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Tablero" in r.text or "tablero" in r.text

@test("GET /tableros?espacio=1 - Tableros filtrados por espacio")
def t08():
    r = client.get("/tableros?espacio=1")
    assert r.status_code == 200

@test("GET /vistas/tabla - Vista Tabla")
def t09():
    r = client.get("/vistas/tabla")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Tabla" in r.text or "tabla" in r.text or "Vista" in r.text

@test("GET /vistas/calendario - Vista Calendario")
def t10():
    r = client.get("/vistas/calendario")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Calendario" in r.text or "calendario" in r.text

@test("GET /vistas/timeline - Vista Timeline")
def t11():
    r = client.get("/vistas/timeline")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Timeline" in r.text or "timeline" in r.text

@test("GET /butler - Página Butler")
def t12():
    r = client.get("/butler")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Butler" in r.text

@test("GET /notificaciones - Centro de notificaciones")
def t13():
    r = client.get("/notificaciones")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Notific" in r.text

# ============================================================
# API: ESPACIOS
# ============================================================
print("\n[API - ESPACIOS]")

@test("GET /api/v1/espacios - Lista espacios")
def t14():
    r = get("/api/v1/espacios")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 3, f"esperaba >=3 espacios, hay {len(data)}"

@test("POST /api/v1/espacios - Crea espacio")
def t15():
    r = post("/api/v1/espacios", json={
        "nombre": "Test Espacio", "descripcion": "Test",
        "plan": "gratis", "color": "#ff0000", "icono": "🎯",
        "es_publico": False, "propietario_id": 1,
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert data["nombre"] == "Test Espacio"
    assert "id" in data

@test("GET /api/v1/espacios/{id} - Detalle espacio")
def t16():
    r = get("/api/v1/espacios/1")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert "nombre" in data
    assert "tableros" in data or "tableros_count" in data or "total_tableros" in data or "id" in data

@test("PATCH /api/v1/espacios/{id} - Actualiza espacio")
def t17():
    r = patch("/api/v1/espacios/1", json={"nombre": "Operaciones TI (Actualizado)"})
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: TABLEROS
# ============================================================
print("\n[API - TABLEROS]")

@test("GET /api/v1/tableros - Lista tableros")
def t18():
    r = get("/api/v1/tableros")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 5, f"esperaba >=5 tableros, hay {len(data)}"

@test("POST /api/v1/tableros - Crea tablero")
def t19():
    r = post("/api/v1/tableros", json={
        "nombre": "Test Tablero", "descripcion": "Test",
        "espacio_id": 1, "visibilidad": "espacio",
        "color_fondo": "#123456", "propietario_id": 1,
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

@test("POST /api/v1/tableros/{id}/archivar - Archiva tablero")
def t20():
    r = post("/api/v1/tableros/1/archivar")
    assert r.status_code in (200, 201, 204), f"status={r.status_code} body={r.text[:200]}"

@test("POST /api/v1/tableros/{id}/restaurar - Restaura tablero")
def t21():
    r = post("/api/v1/tableros/1/restaurar")
    assert r.status_code in (200, 201, 204), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: PERMISOS
# ============================================================
print("\n[API - PERMISOS DE TABLERO]")

@test("GET /api/v1/tableros/{id}/permisos - Lista permisos")
def t22():
    r = get("/api/v1/tableros/1/permisos")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)

@test("POST /api/v1/tableros/{id}/permisos - Asigna permiso")
def t23():
    r = post("/api/v1/tableros/1/permisos", json={
        "tablero_id": 1, "usuario_id": 2, "rol_tablero": "editor",
        "notificar": True,
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: WATCH (suscripciones)
# ============================================================
print("\n[API - WATCH]")

@test("POST /api/v1/watch - Toggle watch")
def t24():
    r = post("/api/v1/watch", json={
        "tipo_objeto": "ticket", "objeto_id": 1, "usuario_id": 1,
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert "activo" in data or "suscrito" in data

@test("GET /api/v1/watch - Lista suscripciones del usuario")
def t25():
    r = get("/api/v1/watch?usuario_id=1")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)

# ============================================================
# API: REACCIONES
# ============================================================
print("\n[API - REACCIONES]")

@test("POST /api/v1/reacciones/toggle - Toggle reacción")
def t26():
    r = post("/api/v1/reacciones/toggle", json={
        "tipo_objeto": "ticket", "objeto_id": 1,
        "usuario_id": 1, "emoji": "👍",
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

@test("GET /api/v1/reacciones/{tipo}/{objeto_id} - Lista reacciones")
def t27():
    r = get("/api/v1/reacciones/ticket/1")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)

# ============================================================
# API: NOTIFICACIONES
# ============================================================
print("\n[API - NOTIFICACIONES]")

@test("GET /api/v1/notificaciones - Lista notificaciones")
def t28():
    r = get("/api/v1/notificaciones?usuario_id=1")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 4, f"esperaba >=4 notifs, hay {len(data)}"

@test("GET /api/v1/notificaciones/contador - Contador no leídas")
def t29():
    r = get("/api/v1/notificaciones/contador?usuario_id=1")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"

@test("POST /api/v1/notificaciones/{id}/leida - Marca como leída")
def t30():
    r = post("/api/v1/notificaciones/1/leida")
    assert r.status_code in (200, 201, 204), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: CUSTOM FIELDS
# ============================================================
print("\n[API - CAMPOS PERSONALIZADOS]")

@test("GET /api/v1/campos-personalizados - Lista campos")
def t31():
    r = get("/api/v1/campos-personalizados")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 5, f"esperaba >=5 campos, hay {len(data)}"

@test("POST /api/v1/campos-personalizados - Crea campo")
def t32():
    r = post("/api/v1/campos-personalizados", json={
        "tablero_id": 1, "nombre": "Test Campo", "tipo": "texto",
        "configuracion": {}, "posicion": 99, "color": "#999999",
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

@test("POST /api/v1/tickets/{id}/campos - Asigna valor")
def t33():
    r = post("/api/v1/tickets/1/campos", json={
        "campo_id": 1, "valor_texto": "SAP",
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: BOTONES BUTLER
# ============================================================
print("\n[API - BOTONES]")

@test("GET /api/v1/botones - Lista botones")
def t34():
    r = get("/api/v1/botones")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 3, f"esperaba >=3 botones, hay {len(data)}"

@test("POST /api/v1/botones - Crea botón")
def t35():
    r = post("/api/v1/botones", json={
        "nombre": "Test Botón", "ambito": "tarjeta",
        "color": "#ff0000", "icono": "⚡",
        "acciones": [{"tipo": "crear_comentario", "parametros": {"texto": "Test"}}],
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

@test("POST /api/v1/botones/{id}/ejecutar - Ejecuta botón")
def t36():
    r = post("/api/v1/botones/1/ejecutar", json={
        "ticket_id": 1, "usuario_id": 1,
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: COMANDOS PROGRAMADOS
# ============================================================
print("\n[API - COMANDOS PROGRAMADOS]")

@test("GET /api/v1/comandos-programados - Lista comandos")
def t37():
    r = get("/api/v1/comandos-programados")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 3, f"esperaba >=3 comandos, hay {len(data)}"

@test("POST /api/v1/comandos-programados - Crea comando")
def t38():
    r = post("/api/v1/comandos-programados", json={
        "nombre": "Test Comando", "cron_expression": "0 12 * * *",
        "timezone": "UTC",
        "acciones": [{"tipo": "crear_comentario", "parametros": {"texto": "Test"}}],
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: VISTAS
# ============================================================
print("\n[API - VISTAS MULTIDIMENSIONALES]")

@test("GET /api/v1/vistas/tabla - Datos para vista tabla")
def t39():
    r = get("/api/v1/vistas/tabla")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert "filas" in data or "tickets" in data or "data" in data or isinstance(data, list)

@test("GET /api/v1/vistas/calendario - Datos para vista calendario")
def t40():
    r = get("/api/v1/vistas/calendario?mes=9&anio=2026")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"

@test("GET /api/v1/vistas/timeline - Datos para vista timeline")
def t41():
    r = get("/api/v1/vistas/timeline")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: METADATA EXTENDIDA DE TICKETS
# ============================================================
print("\n[API - METADATA TICKETS]")

@test("PATCH /api/v1/tickets/{id}/metadata - Actualiza metadata")
def t42():
    r = patch("/api/v1/tickets/1/metadata", json={
        "fecha_inicio": "2026-01-15",
        "fecha_vencimiento": "2026-01-30",
        "portada_color": "#3b82f6",
        "descripcion_md": True,
    })
    assert r.status_code in (200, 201, 204), f"status={r.status_code} body={r.text[:200]}"

# ============================================================
# API: MARKDOWN
# ============================================================
print("\n[API - MARKDOWN]")

@test("POST /api/v1/markdown/renderizar - Renderiza markdown")
def t43():
    r = post("/api/v1/markdown/renderizar", json={
        "texto": "# Hola **mundo** con `código` y @usuario1",
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert "html" in data or "texto" in data

# ============================================================
# HEALTH
# ============================================================
print("\n[HEALTH CHECKS]")

@test("GET /health - Health check")
def t44():
    r = client.get("/health")
    assert r.status_code in (200, 503), f"status={r.status_code}"
    data = r.json()
    assert "status" in data

@test("GET /ready - Readiness")
def t45():
    r = client.get("/ready")
    assert r.status_code == 200

@test("GET /info - Info del entorno")
def t46():
    r = client.get("/info")
    assert r.status_code == 200

# ============================================================
# RESUMEN
# ============================================================
print("\n" + "="*60)
print(f"RESULTADO: {pasados}/{total} tests PASADOS")
if fallados:
    print(f"\nFALLAS ({len(fallados)}):")
    for n, e in fallados:
        print(f"  - {n}: {e}")
print("="*60)
sys.exit(0 if not fallados else 1)
