"""
Smoke test: verifica que tras guardar cambios en el modal de detalle de un
ticket, el backend emite un HX-Trigger con `ticket-guardado` que incluye
`ticket_id` y `estado_id`, y que el endpoint /card-html devuelve el HTML
actualizado de la tarjeta para que el cliente pueda refrescarla en el tablero
sin recargar la página completa.

Este test cubre el bug reportado:
  "Falta un REFRESH de todo el tablero despues de cuando se presiona el
   boton Guardar en la tarjetas cuando son editadas."

El frontend escucha el evento `ticket-guardado` (htmx-events.js), hace un
fetch a /card-html, y reemplaza la tarjeta via outerHTML.
"""
import os
import sys
import json
import tempfile

# Aislar la BD para no tocar la real
TEST_DB = tempfile.mktemp(prefix="test_board_refresh_", suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-testing"
os.environ["AUTO_INIT_DB"] = "false"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Crear BD mínima
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.core.security import hash_password

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    # Usuario admin
    admin = Usuario(
        username="admin",
        email="admin@test.local",
        nombre_completo="Admin Test",
        hashed_password=hash_password("admin123"),
        rol=RolUsuario.ADMINISTRADOR,
        is_active=True,
    )
    db.add(admin)
    db.flush()

    # Estado mínimo
    estado = Estado(
        nombre="Nuevo",
        descripcion="Incidencia recién creada",
        color="#3b82f6",
        orden=1,
        es_inicial=True,
        es_final=False,
        categoria="abierto",
    )
    db.add(estado)
    db.flush()

    # Ticket de prueba
    ticket = Ticket(
        codigo="TST-0001",
        titulo="Título original",
        descripcion="Descripción original",
        tipo=TipoIncidencia.INCIDENCIA,
        prioridad=Prioridad.MEDIA,
        estado_id=estado.id,
        creador_id=admin.id,
    )
    db.add(ticket)
    db.commit()
    ticket_id = ticket.id
    estado_id = estado.id
finally:
    db.close()

# Importar la app DESPUÉS de inicializar la BD
from app.main import app  # noqa: E402

client = TestClient(app)
AUTH = {"X-User-Id": "1"}


results = []
def check(name, ok, detail=""):
    mark = "OK " if ok else "FAIL"
    results.append((ok, name, detail))
    print(f"[{mark}] {name} :: {detail}")


# --------------------------------------------------------------------
# 1) Sanity: /card-html devuelve la tarjeta actual del ticket
# --------------------------------------------------------------------
r = client.get(f"/api/v1/tickets/{ticket_id}/card-html", headers=AUTH)
check(
    "GET /card-html -> 200 con HTML de la tarjeta",
    r.status_code == 200 and "TST-0001" in r.text and "Título original" in r.text,
    f"status={r.status_code} contiene_codigo={'TST-0001' in r.text}",
)
check(
    "GET /card-html -> contiene id=\"ticket-N\"",
    f'id="ticket-{ticket_id}"' in r.text,
    f"id_match={'id=\"ticket-' + str(ticket_id) + '\"' in r.text}",
)

# --------------------------------------------------------------------
# 2) FIX: POST /guardar emite HX-Trigger con ticket-guardado + ticket_id
# --------------------------------------------------------------------
r = client.post(
    f"/api/v1/tickets/{ticket_id}/guardar",
    data={
        "valor_titulo": "Título ACTUALIZADO",
        "valor_descripcion": "Descripción nueva",
        "valor_prioridad": "alta",
        "active_tab": "detalles",
    },
    headers=AUTH,
)
check(
    "POST /guardar -> 200 OK",
    r.status_code == 200,
    f"status={r.status_code}",
)
hx_trigger = r.headers.get("HX-Trigger")
check(
    "POST /guardar -> HX-Trigger presente",
    hx_trigger is not None,
    f"HX-Trigger={hx_trigger!r}",
)
if hx_trigger:
    try:
        triggers = json.loads(hx_trigger)
        check(
            "HX-Trigger contiene evento 'ticket-guardado'",
            "ticket-guardado" in triggers,
            f"keys={list(triggers.keys())}",
        )
        guard = triggers.get("ticket-guardado") or {}
        check(
            "ticket-guardado incluye ticket_id",
            guard.get("ticket_id") == ticket_id,
            f"ticket_id={guard.get('ticket_id')} (esperado {ticket_id})",
        )
        check(
            "ticket-guardado incluye estado_id",
            guard.get("estado_id") == estado_id,
            f"estado_id={guard.get('estado_id')} (esperado {estado_id})",
        )
        check(
            "ticket-guardado incluye lista de campos modificados",
            isinstance(guard.get("campos"), list) and "titulo" in guard.get("campos", []),
            f"campos={guard.get('campos')}",
        )
        # También debe estar el evento complementario 'ticket-updated'
        check(
            "HX-Trigger también incluye 'ticket-updated' con ticket_id",
            "ticket-updated" in triggers
            and (triggers.get("ticket-updated") or {}).get("ticket_id") == ticket_id,
            f"updated={triggers.get('ticket-updated')}",
        )
    except json.JSONDecodeError as e:
        check("HX-Trigger es JSON válido", False, f"json error: {e}")

# --------------------------------------------------------------------
# 3) FIX: /card-html refleja los cambios tras /guardar
# --------------------------------------------------------------------
r = client.get(f"/api/v1/tickets/{ticket_id}/card-html", headers=AUTH)
check(
    "Tras /guardar, /card-html muestra el nuevo título",
    r.status_code == 200 and "Título ACTUALIZADO" in r.text,
    f"status={r.status_code} contiene_nuevo={'Título ACTUALIZADO' in r.text}",
)
check(
    "Tras /guardar, /card-html NO muestra el título antiguo",
    "Título original" not in r.text,
    f"quitado_viejo={'Título original' not in r.text}",
)
check(
    "Tras /guardar, /card-html muestra prioridad ALTA",
    "ALTA" in r.text,
    f"contiene_alta={'ALTA' in r.text}",
)

# --------------------------------------------------------------------
# 4) FIX: /card-html para ticket inexistente -> 404
# --------------------------------------------------------------------
r = client.get("/api/v1/tickets/99999/card-html", headers=AUTH)
check(
    "/card-html con ticket inexistente -> 404",
    r.status_code == 404,
    f"status={r.status_code}",
)

# --------------------------------------------------------------------
# 5) /guardar sin auth -> 401
# --------------------------------------------------------------------
r = client.post(
    f"/api/v1/tickets/{ticket_id}/guardar",
    data={"valor_titulo": "x"},
)
check(
    "/guardar sin autenticación -> 401",
    r.status_code == 401,
    f"status={r.status_code}",
)

# --------------------------------------------------------------------
# 6) /card-html sin auth -> 401
# --------------------------------------------------------------------
r = client.get(f"/api/v1/tickets/{ticket_id}/card-html")
check(
    "/card-html sin autenticación -> 401",
    r.status_code == 401,
    f"status={r.status_code}",
)

# --------------------------------------------------------------------
# 7) FIX: /guardar con múltiples campos actualiza y devuelve todos en 'campos'
# --------------------------------------------------------------------
r = client.post(
    f"/api/v1/tickets/{ticket_id}/guardar",
    data={
        "valor_titulo": "Título v2",
        "valor_descripcion": "Desc v2",
        "valor_prioridad": "critica",
        "valor_asignado_id": str(admin.id),
        "active_tab": "detalles",
    },
    headers=AUTH,
)
check(
    "POST /guardar con múltiples campos -> 200",
    r.status_code == 200,
    f"status={r.status_code}",
)
if r.headers.get("HX-Trigger"):
    triggers = json.loads(r.headers["HX-Trigger"])
    campos = (triggers.get("ticket-guardado") or {}).get("campos") or []
    esperados = {"titulo", "descripcion", "prioridad", "asignado_id"}
    check(
        "ticket-guardado.campos contiene los 4 campos esperados",
        esperados.issubset(set(campos)),
        f"campos={campos} esperados={sorted(esperados)}",
    )

# Verificar en /card-html que la tarjeta refleja la prioridad CRÍTICA
r = client.get(f"/api/v1/tickets/{ticket_id}/card-html", headers=AUTH)
check(
    "Card muestra prioridad CRITICA tras /guardar",
    "CRITICA" in r.text,
    f"contiene_critica={'CRITICA' in r.text}",
)

# --------------------------------------------------------------------
# 8) FIX: el atributo data-prioridad de la tarjeta refleja la nueva prioridad
# --------------------------------------------------------------------
# (Esto valida que el JS listener pueda encontrar/identificar la tarjeta
#  correctamente con la información más reciente del board.)
check(
    "Card tiene data-prioridad='critica'",
    'data-prioridad="critica"' in r.text,
    f"data_match={'data-prioridad=\"critica\"' in r.text}",
)
check(
    "Card tiene data-ticket-id correcto",
    f'data-ticket-id="{ticket_id}"' in r.text,
    f"data_match={'data-ticket-id=\"' + str(ticket_id) + '\"' in r.text}",
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
