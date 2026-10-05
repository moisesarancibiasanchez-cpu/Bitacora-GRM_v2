"""
Tests e2e para el Reporte Diario de Entregas (Feature 6).

Cubre:
  - Permisos: solo rol administrador.
  - Endpoints admin:
      * GET /api/v1/admin/reporte-entregas/plantilla
      * POST /api/v1/admin/reporte-entregas/plantilla
      * GET/POST /api/v1/admin/reporte-entregas/destinatarios
      * POST /api/v1/admin/reporte-entregas/destinatarios/{id}/toggle
      * POST /api/v1/admin/reporte-entregas/destinatarios/{id}/eliminar
      * GET/POST /api/v1/admin/reporte-entregas/estados
      * GET /api/v1/admin/reporte-entregas/entregas
      * GET /api/v1/admin/reporte-entregas/previsualizar
      * POST /api/v1/admin/reporte-entregas/regenerar
"""
import os
import sys
import logging

logging.disable(logging.CRITICAL)

os.environ["DATABASE_URL"] = "sqlite:///./test_reporte_entregas.db"
os.environ["AUTO_INIT_DB"] = "false"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if os.path.exists("./test_reporte_entregas.db"):
    os.remove("./test_reporte_entregas.db")

from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.db.migrations import apply_migrations
from app.main import app

# Importar el paquete de modelos para que SQLAlchemy registre
# TODAS las tablas (incluyendo reporte_entregas_*) antes de
# create_all.
from app.models import (  # noqa: F401
    Estado, Usuario, Ticket, ReportePlantilla,
    ReporteDestinatario, ReporteEntregaDiaria,
)

# Crear todas las tablas (incluye reporte_entregas_*) y aplicar
# migraciones idempotentes (que es donde se añade es_entrega y se
# marcan los estados terminales).
Base.metadata.create_all(bind=engine)
apply_migrations()

# ----------------------------------------------------------------------
#  Seed minimo
# ----------------------------------------------------------------------
from app.core.security import hash_password
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.ticket import Ticket, Prioridad

db = SessionLocal()
try:
    if db.query(Usuario).count() == 0:
        admin = Usuario(
            username="admin",
            email="admin@test.local",
            nombre_completo="Admin Test",
            hashed_password=hash_password("admin123"),
            rol=RolUsuario.ADMINISTRADOR,
            departamento="TI",
        )
        agente = Usuario(
            username="agente1",
            email="agente1@test.local",
            nombre_completo="Agente Test",
            hashed_password=hash_password("agente123"),
            rol=RolUsuario.AGENTE,
            departamento="Soporte",
        )
        db.add_all([admin, agente])
        db.flush()

    if db.query(Estado).count() == 0:
        db.add_all([
            Estado(nombre="Nuevo", orden=1, es_inicial=True,
                    color="#94a3b8", categoria="abierto"),
            Estado(nombre="Entregado", orden=2, es_final=True,
                    es_entrega=True, color="#10b981", categoria="cerrado"),
        ])
        db.flush()

    if db.query(Ticket).count() == 0:
        e_nuevo = db.query(Estado).filter(Estado.nombre == "Nuevo").first()
        ag = db.query(Usuario).filter(Usuario.username == "agente1").first()
        adm = db.query(Usuario).filter(Usuario.username == "admin").first()
        db.add(Ticket(
            codigo="TEST-001",
            titulo="Ticket de prueba",
            descripcion="demo",
            prioridad=Prioridad.MEDIA,
            estado_id=e_nuevo.id,
            creador_id=adm.id,
            asignado_id=ag.id,
        ))

    db.commit()
finally:
    db.close()


def _login(client, username, password):
    r = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, f"login fallo: {r.status_code} {r.text}"
    body = r.json()
    user_id = body.get("user_id") or body.get("id") or body.get("usuario", {}).get("id")
    assert user_id is not None, f"login sin id: {r.text}"
    return str(user_id)


client = TestClient(app)

try:
    print("\n--- Permisos ---")
    r = client.get("/api/v1/admin/reporte-entregas/plantilla")
    assert r.status_code in (401, 403), r.status_code

    agente_id = _login(client, "agente1", "agente123")
    r = client.get(
        "/api/v1/admin/reporte-entregas/plantilla",
        headers={"X-User-Id": agente_id},
    )
    assert r.status_code == 403, r.status_code
    print("   OK agente recibe 403")

    admin_id = _login(client, "admin", "admin123")
    ADMIN = {"X-User-Id": admin_id}

    print("\n--- Plantilla ---")
    r = client.get(
        "/api/v1/admin/reporte-entregas/plantilla", headers=ADMIN
    )
    assert r.status_code == 200, r.text
    pl = r.json()
    assert pl["id"] == 1
    r = client.post(
        "/api/v1/admin/reporte-entregas/plantilla",
        headers=ADMIN,
        data={
            "habilitado": "true",
            "asunto": "[Test] Entregas {{fecha}} ({{cantidad}})",
            "cuerpo_html": "<h1>{{fecha}}</h1><p>Total: {{cantidad}}</p>",
            "cuerpo_texto": "Fecha {{fecha}}: {{cantidad}} entregas",
            "firma": "-- Equipo TI",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    print("   OK plantilla creada/actualizada")

    print("\n--- Destinatarios ---")
    r = client.post(
        "/api/v1/admin/reporte-entregas/destinatarios",
        headers=ADMIN,
        data={
            "email": "ops@test.local",
            "nombre": "Equipo Ops",
            "rol": "agente",
            "notas": "auto",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    dest_id = r.json()["id"]

    r = client.get(
        "/api/v1/admin/reporte-entregas/destinatarios", headers=ADMIN
    )
    assert r.status_code == 200, r.text
    dests = r.json()
    assert any(d["email"] == "ops@test.local" for d in dests)

    r = client.post(
        "/api/v1/admin/reporte-entregas/destinatarios",
        headers=ADMIN,
        data={"email": "ops@test.local", "nombre": "Equipo Ops v2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["creado"] is False
    assert body["id"] == dest_id
    print("   OK upsert detectado como duplicado")

    r = client.post(
        f"/api/v1/admin/reporte-entregas/destinatarios/{dest_id}/toggle",
        headers=ADMIN,
        data={"activo": "false"},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post(
        f"/api/v1/admin/reporte-entregas/destinatarios/{dest_id}/toggle",
        headers=ADMIN,
        data={"activo": "true"},
    )
    assert r.status_code == 200 and r.json()["ok"] is True

    r = client.post(
        f"/api/v1/admin/reporte-entregas/destinatarios/{dest_id}/eliminar",
        headers=ADMIN,
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["eliminado"]["email"] == "ops@test.local"
    print("   OK toggle + eliminar")

    print("\n--- Estados es_entrega ---")
    db = SessionLocal()
    e_nuevo = db.query(Estado).filter(Estado.nombre == "Nuevo").first()
    db.close()
    r = client.post(
        f"/api/v1/admin/reporte-entregas/estados/{e_nuevo.id}/es-entrega",
        headers=ADMIN,
        data={"es_entrega": "true"},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post(
        f"/api/v1/admin/reporte-entregas/estados/{e_nuevo.id}/es-entrega",
        headers=ADMIN,
        data={"es_entrega": "false"},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    print("   OK toggle es_entrega")

    print("\n--- Historico ---")
    r = client.get(
        "/api/v1/admin/reporte-entregas/entregas?dias=7", headers=ADMIN
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "resumen" in payload
    assert "ultimas" in payload
    print("   OK resumen={} dias, ultimas={} tickets".format(
        len(payload["resumen"]), len(payload["ultimas"])
    ))

    print("\n--- Previsualizar / Regenerar ---")
    r = client.get(
        "/api/v1/admin/reporte-entregas/previsualizar", headers=ADMIN
    )
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["ok"] is True
    assert "asunto" in pv and "cuerpo_html" in pv
    print("   OK previsualizar fecha={} cantidad={}".format(
        pv["fecha"], pv["cantidad"]
    ))

    r = client.post(
        "/api/v1/admin/reporte-entregas/regenerar", headers=ADMIN
    )
    assert r.status_code == 200, r.text
    reg = r.json()
    assert "ok" in reg and "task_id" in reg
    print("   OK regenerar task_id={}".format(reg.get("task_id")))

    print("\nTodos los tests pasaron.")
except AssertionError as e:
    print("\nAssertionError: {}".format(e))
    sys.exit(1)
except Exception as e:
    print("\nError inesperado: {}: {}".format(type(e).__name__, e))
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    try:
        if os.path.exists("./test_reporte_entregas.db"):
            os.remove("./test_reporte_entregas.db")
    except Exception:
        pass