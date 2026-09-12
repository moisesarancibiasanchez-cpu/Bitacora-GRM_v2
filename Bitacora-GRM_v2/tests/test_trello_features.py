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
# REGRESIÓN: drag & drop Kanban (datos_catalogo debe ser JSON, no Text)
# Bug: "No se pudo cambiar el estado" porque el UPDATE fallaba con
# sqlite3.ProgrammingError: type 'dict' is not supported
# ============================================================
print("\n[REGRESIÓN - DRAG & DROP KANBAN]")

@test("PATCH /api/v1/tickets/{id}/estado - Drag&drop básico (regresión)")
def t42b():
    """Verifica que el endpoint PATCH de cambio de estado funciona correctamente
    cuando se hace drag&drop (es decir, con orden != None). Este caso activaba
    el bug 'datos_catalogo' al asignar un dict a una columna Text."""
    # 1) Obtener un ticket
    r = get("/api/v1/tickets")
    assert r.status_code == 200, f"listar tickets: {r.status_code}"
    tickets = r.json()
    assert len(tickets) > 0, "no hay tickets para probar"
    t = tickets[0]
    ticket_id = t["id"]
    estado_actual = t["estado_id"]

    # 2) Encontrar una transición válida
    r = get("/api/v1/estados")
    estados = r.json()
    nuevo_estado = None
    for e in estados:
        if e["id"] != estado_actual:
            # Verificar si la transición es válida
            ri = get(f"/api/v1/tickets/{ticket_id}/transicion-info/{e['id']}")
            if ri.status_code == 200 and ri.json().get("valida"):
                nuevo_estado = e["id"]
                break
    if nuevo_estado is None:
        # No hay transición válida, saltar
        return

    # 3) Hacer PATCH simulando drag&drop (con orden)
    r = patch(
        f"/api/v1/tickets/{ticket_id}/estado",
        json={"estado_id": nuevo_estado, "orden": 0, "comentario": None},
    )
    # 200 = OK, 422 = transición no permitida (válido), 500 = BUG
    assert r.status_code in (200, 422), (
        f"BUG REGRESIÓN: PATCH estado devolvió {r.status_code} "
        f"(debe ser 200/422, no 500). Body: {r.text[:300]}"
    )
    # Si es 200, debe devolver HTML de la tarjeta
    if r.status_code == 200:
        assert "kanban-card" in r.text or "ticket-" in r.text, (
            f"Respuesta 200 debe contener HTML de la tarjeta. Body: {r.text[:300]}"
        )

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
# REGRESIÓN: módulo de migraciones idempotente
# Bug: "column estados.tablero_id does not exist" en producción porque
# el esquema de la BD no se migró cuando se añadieron las columnas de
# las features estilo Trello. El módulo app.db.migrations detecta y
# añade las columnas faltantes de forma idempotente.
# ============================================================
print("\n[REGRESIÓN - MIGRACIONES DE ESQUEMA]")

@test("apply_migrations() es idempotente y completa el esquema")
def t47():
    """Verifica que apply_migrations() puede ejecutarse múltiples veces
    sin errores y deja todas las columnas requeridas presentes."""
    from app.db.migrations import apply_migrations, COLUMNS_TO_ADD
    from sqlalchemy import inspect
    insp = inspect(engine)
    # 1) Primera ejecución: debe añadir las columnas que falten
    stats1 = apply_migrations()
    assert stats1["errors"] == 0, f"errores en primera ejecución: {stats1}"
    # 2) Verificar que las columnas requeridas ahora existen
    for table, columns in COLUMNS_TO_ADD.items():
        existing = {c["name"] for c in insp.get_columns(table)}
        for col in columns:
            assert col in existing, (
                f"BUG REGRESIÓN: columna {table}.{col} no fue añadida. "
                f"Existentes: {sorted(existing)}"
            )
    # 3) Segunda ejecución: debe ser NO-OP (idempotencia)
    stats2 = apply_migrations()
    assert stats2["applied"] == 0, (
        f"idempotencia rota: 2ª ejecución añadió {stats2['applied']} columnas, "
        f"esperaba 0"
    )
    assert stats2["skipped"] >= len(COLUMNS_TO_ADD["estados"]) + len(
        COLUMNS_TO_ADD["tickets"]
    ), f"2ª ejecución debería saltar las columnas existentes: {stats2}"

# ============================================================
# REGRESIÓN: endpoints de modal aceptan form-data (HTMX)
# Bug: el botón "+ Nueva Incidencia" no abría el modal y al añadir
# comentarios / checklists / adjuntos dentro de una tarjeta kanban,
# los formularios HTMX (form-data) eran rechazados con 422 porque
# los endpoints solo aceptaban JSON. La consecuencia era que el
# usuario no podía editar nada desde la UI.
# Fix: los endpoints /comentarios, /checklists y /adjuntos ahora
# aceptan tanto form-data (HTMX) como JSON (API tradicional) y,
# cuando llega el header HX-Request, devuelven el modal
# re-renderizado en HTML para hacer el swap in-place.
# ============================================================
print("\n[REGRESIÓN - FORM-DATA PARA MODAL]")

# Asegurar que tenemos al menos un ticket de prueba
from app.models.ticket import Ticket
from app.models.estado import Estado
db_test = SessionLocal()
try:
    ticket_test = db_test.query(Ticket).first()
    if not ticket_test:
        # Crear ticket mínimo para los tests
        estado = db_test.query(Estado).first()
        ticket_test = Ticket(
            codigo="TST-001",
            titulo="Ticket de prueba form-data",
            descripcion="Para tests de regresión",
            estado_id=estado.id if estado else 1,
            creador_id=1,
        )
        db_test.add(ticket_test)
        db_test.commit()
        db_test.refresh(ticket_test)
    TICKET_ID = ticket_test.id
finally:
    db_test.close()

@test("POST /tickets/{id}/comentarios con form-data devuelve HTML (HTMX)")
def t48():
    """El formulario HTMX envía application/x-www-form-urlencoded.
    El endpoint debe aceptarlo y devolver HTML para hacer swap del modal."""
    r = post(
        f"/api/v1/tickets/{TICKET_ID}/comentarios",
        data={"texto": "Comentario de regresión form-data"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    # Debe ser HTML con el modal
    assert "<!DOCTYPE" in r.text or "<html" in r.text or 'data-modal="detalle-ticket"' in r.text, (
        f"Se esperaba HTML del modal, se obtuvo: {r.text[:200]}"
    )
    # Debe incluir el comentario recién creado
    assert "Comentario de regresión form-data" in r.text, (
        f"El comentario no aparece en el HTML devuelto: {r.text[:300]}"
    )

@test("POST /tickets/{id}/comentarios con JSON devuelve 200/201 (API tradicional)")
def t49():
    """Compatibilidad hacia atrás: los clientes que envíen JSON
    deben seguir funcionando sin cambios."""
    r = post(
        f"/api/v1/tickets/{TICKET_ID}/comentarios",
        json={"texto": "Comentario JSON tradicional", "es_interno": False},
    )
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}"
    data = r.json()
    assert "id" in data, f"Respuesta sin id: {data}"
    assert "Comentario JSON tradicional" in data.get("texto", "")

@test("POST /tickets/{id}/checklists con form-data (HTMX) crea checklist y devuelve HTML")
def t50():
    """El form de nueva checklist debe apuntar a /checklists (plural)
    y el endpoint debe aceptar form-data devolviendo el modal."""
    r = post(
        f"/api/v1/tickets/{TICKET_ID}/checklists",
        data={"titulo": "Checklist regresión form-data"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    assert 'data-modal="detalle-ticket"' in r.text or "<!DOCTYPE" in r.text, (
        f"Se esperaba HTML del modal: {r.text[:200]}"
    )
    assert "Checklist regresión form-data" in r.text, (
        f"La checklist no aparece en el HTML devuelto: {r.text[:300]}"
    )

@test("POST /tickets/{id}/adjuntos acepta multipart/form-data y devuelve HTML")
def t51():
    """Subida de archivo real con multipart/form-data."""
    import io
    contenido = b"%PDF-1.4\n%contenido de prueba para regresion\n%%EOF"
    files = {"archivo": ("regresion.pdf", io.BytesIO(contenido), "application/pdf")}
    r = post(
        f"/api/v1/tickets/{TICKET_ID}/adjuntos",
        files=files,
        data={"descripcion": "PDF de regresión"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
    # Debe incluir el nombre del archivo en el HTML re-renderizado
    assert "regresion.pdf" in r.text, (
        f"El adjunto no aparece en el HTML devuelto: {r.text[:300]}"
    )


# ============================================================
# SPRINT 1 - FEATURES TRELLO-LIKE AVANZADAS
# ============================================================
print("\n[SPRINT 1 - TRELLO AVANZADO]")

@test("GET /dashboard - Renderiza pagina de dashboard con KPIs")
def t52():
    r = client.get("/dashboard")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Dashboard" in r.text or "dashboard" in r.text
    assert "kpi" in r.text.lower() or "Cargando" in r.text or "Tickets" in r.text

@test("GET /api/v1/metricas/resumen - Devuelve KPIs y agregaciones")
def t53():
    r = get("/api/v1/metricas/resumen?dias=30")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    assert "totales" in data, f"Falta clave 'totales': {list(data.keys())}"
    assert "total" in data["totales"]
    assert "sla" in data
    assert "porcentaje_cumplimiento" in data["sla"]
    assert "distribucion_estado" in data
    assert "distribucion_prioridad" in data
    assert "actividad_por_dia" in data
    assert isinstance(data["distribucion_estado"], list)
    assert isinstance(data["actividad_por_dia"], list)

@test("GET /api/v1/metricas/resumen con diferentes dias (7, 30, 90)")
def t54():
    for d in (7, 30, 90):
        r = get(f"/api/v1/metricas/resumen?dias={d}")
        assert r.status_code == 200, f"dias={d} status={r.status_code}"
        data = r.json()
        assert data["totales"]["total"] >= 0

@test("GET /api/v1/buscar?q=incidencia - Busqueda global multi-entidad")
def t55():
    r = get("/api/v1/buscar?q=incidencia&limite=5")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    assert "tickets" in data, f"Falta clave 'tickets': {list(data.keys())}"
    assert isinstance(data["tickets"], list)
    if data["tickets"]:
        first = data["tickets"][0]
        assert "titulo" in first
        assert "url" in first

@test("GET /api/v1/buscar?q=admin - Encuentra usuarios")
def t56():
    r = get("/api/v1/buscar?q=admin&limite=5")
    assert r.status_code == 200, f"status={r.status_code}"
    data = r.json()
    assert "usuarios" in data
    if data["usuarios"]:
        for u in data["usuarios"]:
            assert "titulo" in u
            assert "url" in u

@test("GET /api/v1/buscar?q=xyz_no_existe - Devuelve resultados vacios")
def t57():
    r = get("/api/v1/buscar?q=xyz_no_existe_abc&limite=5")
    assert r.status_code == 200, f"status={r.status_code}"
    data = r.json()
    assert isinstance(data["tickets"], list)

@test("POST /api/v1/tickets/{id}/duplicar - Duplica ticket con (Copia)")
def t58():
    r = post(f"/api/v1/tickets/{TICKET_ID}/duplicar")
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    assert "id" in data, f"Respuesta sin id: {data}"
    assert "codigo" in data
    assert data["id"] != TICKET_ID

@test("GET /api/v1/tickets/exportar/csv - Devuelve CSV descargable")
def t59():
    r = get("/api/v1/tickets/exportar/csv")
    assert r.status_code == 200, f"status={r.status_code}"
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct or "csv" in ct, f"Content-Type inesperado: {ct}"
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd, f"Content-Disposition inesperado: {cd}"
    content = r.text
    assert "codigo" in content.lower() or "GRM" in content
    lines = content.strip().split("\n")
    assert len(lines) >= 2, f"CSV sin filas de datos: {len(lines)} lineas"

@test("GET /api/v1/catalogos/usuarios - Lista usuarios para filtros")
def t60():
    r = get("/api/v1/catalogos/usuarios")
    assert r.status_code == 200, f"status={r.status_code}"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "id" in data[0]
    assert "nombre_completo" in data[0]

@test("GET /api/v1/catalogos/etiquetas - Lista etiquetas para filtros")
def t61():
    r = get("/api/v1/catalogos/etiquetas")
    assert r.status_code == 200, f"status={r.status_code}"
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "id" in data[0]
        assert "nombre" in data[0]
        assert "color" in data[0]

@test("GET /api/v1/tickets/buscar/query?q=... - Endpoint dedicado de tickets")
def t62():
    r = get("/api/v1/tickets/buscar/query?q=test&limit=10")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "id" in data[0]
        assert "codigo" in data[0]

@test("GET /api/v1/tickets/buscar/query con filtros (prioridad, archivado)")
def t63():
    r = get("/api/v1/tickets/buscar/query?prioridad=critica&archivado=false&limit=5")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    assert isinstance(data, list)

@test("GET /api/v1/butler/reglas - Lista reglas Butler")
def t64():
    r = get("/api/v1/butler/reglas")
    assert r.status_code == 200, f"status={r.status_code}"
    data = r.json()
    assert isinstance(data, list)

@test("POST /api/v1/butler/reglas - Crea regla Butler")
def t65():
    r = post("/api/v1/butler/reglas", json={
        "nombre": "Test regla Trello",
        "disparador": "ticket_creado",
        "descripcion": "Regla de prueba creada por test",
        "acciones": [{"tipo": "set_estado", "parametros": {"estado_id": 2}}],
        "activo": True,
    })
    assert r.status_code in (200, 201), f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    assert "id" in data
    assert data["nombre"] == "Test regla Trello"
    assert data["disparador"] == "ticket_creado"
    assert data["activo"] is True

@test("POST /api/v1/butler/reglas con disparador invalido - Devuelve 422")
def t66():
    r = post("/api/v1/butler/reglas", json={
        "nombre": "Regla invalida",
        "disparador": "disparador_inexistente",
        "acciones": [{"tipo": "set_estado", "parametros": {}}],
    })
    assert r.status_code in (400, 422), f"Esperaba 400/422, obtuvo {r.status_code}"

@test("PATCH /api/v1/butler/reglas/{id} - Actualiza regla (toggle activo)")
def t67():
    r1 = post("/api/v1/butler/reglas", json={
        "nombre": "Regla toggle test",
        "disparador": "ticket_etiquetado",
        "acciones": [{"tipo": "add_etiqueta", "parametros": {"etiqueta_id": 1}}],
    })
    assert r1.status_code in (200, 201), f"status={r1.status_code}"
    rid = r1.json()["id"]
    r2 = patch(f"/api/v1/butler/reglas/{rid}", json={"activo": False})
    assert r2.status_code == 200, f"status={r2.status_code} body={r2.text[:300]}"
    assert r2.json()["activo"] is False

@test("DELETE /api/v1/butler/reglas/{id} - Elimina regla")
def t68():
    r1 = post("/api/v1/butler/reglas", json={
        "nombre": "Regla a eliminar",
        "disparador": "cada_dia",
        "acciones": [{"tipo": "notify", "parametros": {"mensaje": "test"}}],
    })
    assert r1.status_code in (200, 201)
    rid = r1.json()["id"]
    r2 = delete(f"/api/v1/butler/reglas/{rid}")
    assert r2.status_code in (200, 204), f"status={r2.status_code} body={r2.text[:300]}"

@test("GET /kanban incluye el panel de filtros")
def t69():
    r = client.get("/kanban")
    assert r.status_code == 200
    assert 'id="toggle-filtros"' in r.text, "Falta el boton de filtros"
    assert 'id="panel-filtros"' in r.text, "Falta el panel de filtros"
    assert 'filtro-q' in r.text, "Falta el input de busqueda"
    assert 'filtro-prioridad' in r.text, "Falta el filtro de prioridad"

@test("GET /kanban incluye command palette (boton + script)")
def t70():
    r = client.get("/kanban")
    assert r.status_code == 200
    assert 'id="command-palette-trigger"' in r.text, "Falta el trigger de command palette"
    assert 'command-palette.js' in r.text, "Falta la referencia al JS del command palette"
    assert 'command-palette-root' in r.text, "Falta el contenedor del command palette"


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

