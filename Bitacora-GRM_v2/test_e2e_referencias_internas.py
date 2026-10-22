#!/usr/bin/env python3
"""
End-to-end test para FEATURE 5: Referencias Internas entre tickets.

Cubre 10+ escenarios:
  1.  Setup (usuarios + 4 tickets)
  2.  Catálogo de tipos válidos (tipos_validos)
  3.  TIPO_INVERSO (padre ↔ hijo, bloquea ↔ bloqueado_por, simétricos)
  4.  Agregar referencia exitosa → graba auditoría
  5.  Rechazar duplicado exacto (mismo origen/destino/tipo)
  6.  Rechazar auto-referencia
  7.  Rechazar tipo inválido
  8.  Rechazar ticket origen inexistente
  9.  Rechazar ticket destino inexistente
  10. listar_para_ticket: bidireccional (origen→destino + destino→origen)
  11. listar_para_ticket: agrupación por dirección (saliente vs entrante)
  12. Eliminar referencia → graba auditoría + desaparece de listados
  13. Autocompletar excluye el ticket actual
  14. Autocompletar vacío cuando query vacío
  15. Smoke test: API endpoints (FastAPI TestClient) — POST/GET/DELETE/GET tipos
"""
import os
import sys
import json
import tempfile
import logging
import warnings

# Silenciar logs/ruido
logging.disable(logging.CRITICAL)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
warnings.filterwarnings("ignore")

# === Setup BD temporal =====================================================
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret-para-e2e-referencias"
os.environ["ALLOW_XUSER_HEADER"] = "true"

# === Imports con la BD ya apuntando al archivo temporal =====================
from app.db.session import engine
from app.db.base import Base
import app.models  # noqa: F401, E402  -- necesario para que SQLAlchemy descubra TODOS los modelos
Base.metadata.create_all(bind=engine)

from fastapi.testclient import TestClient
from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.espacio import Espacio, Tablero
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.models.auditoria import Auditoria
from app.models.ticket_referencia import (
    TicketReferencia, TipoReferencia, TIPO_INVERSO,
)
from app.core.security import hash_password
from app.services.referencia_service import (
    TicketReferenciaService, ReferenciaError, TIPO_REFERENCIA_NOMBRES,
)
from app.main import app  # noqa: E402

# === Contadores de resultado ================================================
_RESULTADOS = {"ok": 0, "fail": 0, "errores": []}


def _check(label: str, condicion: bool, detalle: str = ""):
    """Assert con contador."""
    if condicion:
        _RESULTADOS["ok"] += 1
        print(f"  [OK]   {label}")
    else:
        _RESULTADOS["fail"] += 1
        msg = f"{label}" + (f" — {detalle}" if detalle else "")
        _RESULTADOS["errores"].append(msg)
        print(f"  [FAIL] {msg}")


def _check_eq(label: str, esperado, real):
    _check(
        label,
        esperado == real,
        f"esperado={esperado!r} real={real!r}",
    )


def _check_contains(label: str, needle, haystack):
    _check(
        label,
        needle in haystack,
        f"needle={needle!r} no aparece en {haystack!r}",
    )


# ============================================================================
# SETUP
# ============================================================================
print("=" * 78)
print("  E2E — FEATURE 5: Referencias Internas entre tickets")
print("=" * 78)

db = SessionLocal()
try:
    # ---- Usuarios ----
    admin = Usuario(
        username="admin", email="admin@test.com",
        nombre_completo="Admin Sistema",
        rol=RolUsuario.ADMINISTRADOR,
        hashed_password=hash_password("test1234"),
        is_active=True,
    )
    db.add(admin); db.commit(); db.refresh(admin)

    ana = Usuario(
        username="ana", email="ana@test.com",
        nombre_completo="Ana QA",
        rol=RolUsuario.AGENTE,
        hashed_password=hash_password("x"),
        is_active=True,
    )
    db.add(ana); db.commit(); db.refresh(ana)

    # ---- Estado + Espacio + Tablero ----
    estado_nuevo = Estado(
        nombre="Nuevo", orden=1, color="#888", categoria="abierto",
    )
    db.add(estado_nuevo); db.commit(); db.refresh(estado_nuevo)

    esp = Espacio(nombre="Espacio Refs", propietario_id=admin.id)
    db.add(esp); db.commit(); db.refresh(esp)
    tablero = Tablero(
        nombre="Tablero Refs", espacio_id=esp.id, propietario_id=admin.id,
    )
    db.add(tablero); db.commit(); db.refresh(tablero)

    # ---- Tickets: 4 en total para múltiples enlaces cruzados ----
    t1 = Ticket(
        codigo="REF-001", titulo="Error en login QA",
        descripcion="Login falla con SSO en QA",
        prioridad=Prioridad.ALTA, tipo=TipoIncidencia.INCIDENCIA,
        estado_id=estado_nuevo.id, tablero_id=tablero.id,
        creador_id=admin.id, asignado_id=admin.id,
        hu_o_caso_prueba="HU-LOGIN-001",
    )
    t2 = Ticket(
        codigo="REF-002", titulo="Error en login PROD",
        descripcion="Mismo bug en producción",
        prioridad=Prioridad.CRITICA, tipo=TipoIncidencia.INCIDENCIA,
        estado_id=estado_nuevo.id, tablero_id=tablero.id,
        creador_id=admin.id, asignado_id=admin.id,
    )
    t3 = Ticket(
        codigo="REF-003", titulo="Tarea hija: agregar MFA",
        descripcion="Subtarea de seguridad",
        prioridad=Prioridad.MEDIA, tipo=TipoIncidencia.INCIDENCIA,
        estado_id=estado_nuevo.id, tablero_id=tablero.id,
        creador_id=ana.id, asignado_id=ana.id,
    )
    t4 = Ticket(
        codigo="REF-004", titulo="Ticket que bloquea deploy",
        descripcion="Esperando fix de BD",
        prioridad=Prioridad.ALTA, tipo=TipoIncidencia.INCIDENCIA,
        estado_id=estado_nuevo.id, tablero_id=tablero.id,
        creador_id=admin.id, asignado_id=admin.id,
    )
    for t in (t1, t2, t3, t4):
        db.add(t)
    db.commit()
    for t in (t1, t2, t3, t4):
        db.refresh(t)
    print(f"[setup] tickets creados: t1={t1.id} t2={t2.id} t3={t3.id} t4={t4.id}")
finally:
    db.close()


# ============================================================================
# ESCENARIO 2: catálogo de tipos válidos
# ============================================================================
print("\n[2] Catálogo de tipos válidos")
tipos = TicketReferenciaService.tipos_validos()
_check("tipos_validos retorna 6 tipos", len(tipos) == 6, f"got {len(tipos)}")
valores = {t["value"] for t in tipos}
esperados = {
    "relacionado", "duplicado", "padre", "hijo",
    "bloquea", "bloqueado_por",
}
_check(
    "tipos_validos contiene todos los esperados",
    valores == esperados,
    f"faltan={esperados - valores} sobran={valores - esperados}",
)
_check(
    "Cada tipo tiene 'nombre' legible",
    all(t.get("nombre") for t in tipos),
)


# ============================================================================
# ESCENARIO 3: TIPO_INVERSO
# ============================================================================
print("\n[3] Mapeo TIPO_INVERSO (semántica de reflejos)")
_check_eq("padre ↔ hijo",
          "hijo", TicketReferenciaService.tipo_inverso("padre"))
_check_eq("hijo ↔ padre",
          "padre", TicketReferenciaService.tipo_inverso("hijo"))
_check_eq("bloquea ↔ bloqueado_por",
          "bloqueado_por",
          TicketReferenciaService.tipo_inverso("bloquea"))
_check_eq("bloqueado_por ↔ bloquea",
          "bloquea",
          TicketReferenciaService.tipo_inverso("bloqueado_por"))
_check_eq("relacionado es simétrico",
          "relacionado",
          TicketReferenciaService.tipo_inverso("relacionado"))
_check_eq("duplicado es simétrico",
          "duplicado",
          TicketReferenciaService.tipo_inverso("duplicado"))
_check_eq("tipo_inverso con valor inválido → None",
          None,
          TicketReferenciaService.tipo_inverso("xyz"))


# ============================================================================
# ESCENARIO 4: agregar referencia exitosa
# ============================================================================
print("\n[4] Agregar referencia (caso feliz)")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    ref = svc.agregar(
        ticket_origen_id=t1.id,
        ticket_referenciado_id=t2.id,
        tipo="duplicado",
        nota="Mismo bug reportado en QA y PROD",
        creado_por_id=admin.id,
    )
    _check("agregar retorna instancia", isinstance(ref, TicketReferencia))
    _check_eq("tipo almacenado", "duplicado", ref.tipo.value)
    _check_eq("origen coincide", t1.id, ref.ticket_origen_id)
    _check_eq("destino coincide", t2.id, ref.ticket_referenciado_id)
    _check_eq("nota almacenada", "Mismo bug reportado en QA y PROD", ref.nota)
    _check("created_at poblado", ref.created_at is not None)
    _check_eq("creado_por_id", admin.id, ref.creado_por_id)

    # === Auditoría: debe haberse registrado 'referencia_agregada' ===
    aud = (
        db.query(Auditoria)
        .filter(
            Auditoria.ticket_id == t1.id,
            Auditoria.accion == "referencia_agregada",
        )
        .first()
    )
    _check("Auditoría 'referencia_agregada' registrada", aud is not None)
    if aud:
        _check("valor_nuevo contiene tipo", "duplicado" in str(aud.valor_nuevo))
finally:
    db.close()


# ============================================================================
# ESCENARIO 5: rechazo por duplicado
# ============================================================================
print("\n[5] Rechazar duplicado exacto (misma tripla origen/destino/tipo)")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    try:
        svc.agregar(
            ticket_origen_id=t1.id,
            ticket_referenciado_id=t2.id,
            tipo="duplicado",  # MISMO tipo que el anterior
        )
        _check("Debió lanzar ReferenciaError", False, "no se lanzó excepción")
    except ReferenciaError as e:
        _check_eq("código de error", "duplicado", e.codigo)
finally:
    db.close()


# ============================================================================
# ESCENARIO 6: rechazo por auto-referencia
# ============================================================================
print("\n[6] Rechazar auto-referencia")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    try:
        svc.agregar(
            ticket_origen_id=t1.id,
            ticket_referenciado_id=t1.id,  # mismo ticket!
            tipo="relacionado",
        )
        _check("Debió lanzar ReferenciaError", False, "no se lanzó excepción")
    except ReferenciaError as e:
        _check_eq("código de error", "auto_referencia", e.codigo)
finally:
    db.close()


# ============================================================================
# ESCENARIO 7: rechazo por tipo inválido
# ============================================================================
print("\n[7] Rechazar tipo inválido")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    try:
        svc.agregar(
            ticket_origen_id=t1.id,
            ticket_referenciado_id=t2.id,
            tipo="inventado",
        )
        _check("Debió lanzar ReferenciaError", False, "no se lanzó excepción")
    except ReferenciaError as e:
        _check_eq("código de error", "tipo_invalido", e.codigo)
finally:
    db.close()


# ============================================================================
# ESCENARIO 8: rechazo por origen inexistente
# ============================================================================
print("\n[8] Rechazar origen inexistente")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    try:
        svc.agregar(
            ticket_origen_id=999999,  # no existe
            ticket_referenciado_id=t2.id,
            tipo="relacionado",
        )
        _check("Debió lanzar ReferenciaError", False, "no se lanzó excepción")
    except ReferenciaError as e:
        _check_eq("código de error", "origen_inexistente", e.codigo)
finally:
    db.close()


# ============================================================================
# ESCENARIO 9: rechazo por destino inexistente
# ============================================================================
print("\n[9] Rechazar destino inexistente")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    try:
        svc.agregar(
            ticket_origen_id=t1.id,
            ticket_referenciado_id=999999,
            tipo="relacionado",
        )
        _check("Debió lanzar ReferenciaError", False, "no se lanzó excepción")
    except ReferenciaError as e:
        _check_eq("código de error", "destino_inexistente", e.codigo)
finally:
    db.close()


# ============================================================================
# ESCENARIO 10: listar_para_ticket (consulta bidireccional)
# ============================================================================
print("\n[10] listar_para_ticket (consulta bidireccional)")
# Creamos más referencias: t1→t3 (padre), t4→t1 (bloquea)
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    svc.agregar(
        ticket_origen_id=t1.id, ticket_referenciado_id=t3.id,
        tipo="padre", nota="REF-003 es hija de REF-001",
    )
    svc.agregar(
        ticket_origen_id=t4.id, ticket_referenciado_id=t1.id,
        tipo="bloquea",
    )
finally:
    db.close()

# t1 debe ver 3 referencias:
#   - saliente → t2 (duplicado)
#   - saliente → t3 (padre)
#   - entrante ← t4 (bloquea)
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    refs_t1 = svc.listar_para_ticket(t1.id)
    _check_eq("t1 tiene 3 referencias", 3, len(refs_t1))

    # Verificar direcciones
    dirs = sorted([r["direccion"] for r in refs_t1])
    _check_eq("mezcla saliente/entrante",
              ["entrante", "saliente", "saliente"], dirs)

    # Verificar tipos
    tipos_vistos = sorted([r["tipo"] for r in refs_t1])
    _check_eq("tipos correctos", ["bloquea", "duplicado", "padre"], tipos_vistos)

    # La saliente 'padre' debe apuntar a t3 (codigo REF-003)
    ref_padre = next(
        (r for r in refs_t1 if r["tipo"] == "padre"), None,
    )
    _check("referencia padre encontrada", ref_padre is not None)
    if ref_padre:
        _check_eq("padre → t3",
                  t3.id, ref_padre["ticket_id"])
        _check_eq("codigo destino", "REF-003", ref_padre["ticket_codigo"])
        _check_eq("tipo_nombre legible", "Es tarea hija de",
                  ref_padre["tipo_nombre"])

    # La entrante 'bloquea' debe venir de t4
    ref_bloq = next(
        (r for r in refs_t1 if r["tipo"] == "bloquea"), None,
    )
    _check("referencia bloquea encontrada", ref_bloq is not None)
    if ref_bloq:
        _check_eq("bloquea desde t4",
                  t4.id, ref_bloq["ticket_id"])
        _check_eq("dirección entrante",
                  "entrante", ref_bloq["direccion"])
finally:
    db.close()


# ============================================================================
# ESCENARIO 11: agrupar por dirección (lo que la UI necesita)
# ============================================================================
print("\n[11] Agrupar por dirección (saliente vs entrante)")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    refs_t1 = svc.listar_para_ticket(t1.id)
    salientes = [r for r in refs_t1 if r["direccion"] == "saliente"]
    entrantes = [r for r in refs_t1 if r["direccion"] == "entrante"]
    _check_eq("2 salientes", 2, len(salientes))
    _check_eq("1 entrante", 1, len(entrantes))

    # t2 debe ver 1 sola referencia (entrante desde t1)
    refs_t2 = svc.listar_para_ticket(t2.id)
    _check_eq("t2 ve 1 referencia", 1, len(refs_t2))
    _check_eq("t2 la ve como entrante",
              "entrante", refs_t2[0]["direccion"])
    _check_eq("t2 ve desde t1", t1.id, refs_t2[0]["ticket_id"])
finally:
    db.close()


# ============================================================================
# ESCENARIO 12: eliminar referencia + auditoría
# ============================================================================
print("\n[12] Eliminar referencia (auditoría)")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    # Obtenemos la referencia duplicado t1→t2
    ref_inicial = (
        db.query(TicketReferencia)
        .filter(
            TicketReferencia.ticket_origen_id == t1.id,
            TicketReferencia.ticket_referenciado_id == t2.id,
            TicketReferencia.tipo == "duplicado",
        )
        .first()
    )
    _check("ref duplicado existe antes de eliminar", ref_inicial is not None)
    ref_id = ref_inicial.id if ref_inicial else None

    # Eliminar
    eliminado = svc.eliminar(ref_id, usuario_id=admin.id)
    _check("eliminar retorna True", eliminado is True)

    # Debe haber desaparecido
    post = svc.obtener(ref_id)
    _check("referencia ya no existe", post is None)

    # listar_para_ticket(t1) debe tener ahora 2 (no 3)
    refs_post = svc.listar_para_ticket(t1.id)
    _check_eq("t1 ahora tiene 2 refs", 2, len(refs_post))

    # Auditoría de eliminación registrada
    aud_elim = (
        db.query(Auditoria)
        .filter(
            Auditoria.ticket_id == t1.id,
            Auditoria.accion == "referencia_eliminada",
        )
        .first()
    )
    _check("Auditoría 'referencia_eliminada' registrada", aud_elim is not None)

    # Eliminar ID inexistente → False
    _check_eq("eliminar id inexistente retorna False",
              False, svc.eliminar(999999))
finally:
    db.close()


# ============================================================================
# ESCENARIO 13: autocompletar excluye el ticket actual
# ============================================================================
print("\n[13] Autocompletar excluye el ticket actual")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    # Búsqueda amplia: query="REF" debería matchear los 4 tickets
    todos = svc.buscar_tickets_para_autocompletar(query="REF", limit=50)
    _check_eq("autocompletar 'REF' ve los 4 tickets",
              4, len(todos))

    # Excluyendo t1, deben quedar 3
    sin_t1 = svc.buscar_tickets_para_autocompletar(
        query="REF", exclude_ticket_id=t1.id, limit=50,
    )
    _check_eq("excluyendo t1 → 3 tickets", 3, len(sin_t1))
    _check(
        "t1 NO aparece en resultados",
        all(r["id"] != t1.id for r in sin_t1),
    )

    # Búsqueda específica por HU
    por_hu = svc.buscar_tickets_para_autocompletar(query="HU-LOGIN-001")
    _check_eq("búsqueda por HU devuelve t1",
              1, len(por_hu))
    if por_hu:
        _check_eq("código match", "REF-001", por_hu[0]["codigo"])
finally:
    db.close()


# ============================================================================
# ESCENARIO 14: autocompletar con query vacío
# ============================================================================
print("\n[14] Autocompletar con query vacío")
db = SessionLocal()
try:
    svc = TicketReferenciaService(db)
    vacio = svc.buscar_tickets_para_autocompletar(query="")
    _check_eq("query vacío → 0 resultados", 0, len(vacio))
    espacios = svc.buscar_tickets_para_autocompletar(query="   ")
    _check_eq("query solo espacios → 0 resultados", 0, len(espacios))
finally:
    db.close()


# ============================================================================
# ESCENARIO 15: smoke test de los endpoints REST vía FastAPI TestClient
# ============================================================================
print("\n[15] Smoke test endpoints REST (FastAPI TestClient)")

# Autenticamos via /auth/login-form y usamos las cookies resultantes.
client = TestClient(app)

# Login real del admin (mismo flujo que el frontend con el formulario HTML).
r_login = client.post(
    "/api/v1/auth/login-form",
    data={"username": "admin", "password": "test1234"},
    follow_redirects=False,
)
_check_eq("Login admin → 200", 200, r_login.status_code)
if r_login.status_code != 200:
    print(f"  DETALLE LOGIN: status={r_login.status_code} body={r_login.text[:200]}")
    sys.exit(1)
_cookies = r_login.cookies


def _hdr():
    return {}  # Las cookies van en el kwarg ``cookies`` de TestClient

# 15.1 GET /api/v1/referencias/tipos
r = client.get("/api/v1/referencias/tipos", headers=_hdr(), cookies=_cookies)
_check_eq("GET /referencias/tipos → 200", 200, r.status_code)
if r.status_code == 200:
    body = r.json()
    _check_eq("tipos endpoint retorna 6", 6, len(body))
    _check(
        "primer tipo es 'relacionado'",
        any(t["value"] == "relacionado" for t in body),
    )

# 15.2 POST /api/v1/tickets/{t1}/referencias  (crear una nueva)
payload = {
    "ticket_referenciado_id": t3.id,
    "tipo": "relacionado",
    "nota": "Smoke test via API",
}
r = client.post(
    f"/api/v1/tickets/{t1.id}/referencias",
    json=payload, headers=_hdr(), cookies=_cookies,
)
_check_eq("POST /tickets/{}/referencias → 201".format(t1.id),
          201, r.status_code)
created_id = None
if r.status_code == 201:
    body = r.json()
    created_id = body.get("id")
    _check_eq("tipo en respuesta", "relacionado", body.get("tipo"))
    _check_eq("dirección saliente", "saliente", body.get("direccion"))
    _check_eq("destino en respuesta", t3.id, body.get("ticket_id"))

# 15.3 POST duplicado → 409
r2 = client.post(
    f"/api/v1/tickets/{t1.id}/referencias",
    json=payload, headers=_hdr(), cookies=_cookies,
)
_check_eq("Duplicado exacto → 409", 409, r2.status_code)

# 15.4 POST auto-referencia → 409
r3 = client.post(
    f"/api/v1/tickets/{t1.id}/referencias",
    json={
        "ticket_referenciado_id": t1.id,
        "tipo": "relacionado",
    },
    headers=_hdr(), cookies=_cookies,
)
_check_eq("Auto-referencia → 409", 409, r3.status_code)
if r3.status_code == 409:
    body = r3.json()
    detail = body.get("detail", {})
    _check_eq("código en detail", "auto_referencia", detail.get("codigo"))

# 15.5 POST tipo inválido → 400
r4 = client.post(
    f"/api/v1/tickets/{t1.id}/referencias",
    json={"ticket_referenciado_id": t3.id, "tipo": "xyz"},
    headers=_hdr(), cookies=_cookies,
)
_check_eq("Tipo inválido → 400", 400, r4.status_code)

# 15.6 POST destino inexistente → 400
r5 = client.post(
    f"/api/v1/tickets/{t1.id}/referencias",
    json={"ticket_referenciado_id": 999999, "tipo": "relacionado"},
    headers=_hdr(), cookies=_cookies,
)
_check_eq("Destino inexistente → 400", 400, r5.status_code)

# 15.7 GET /api/v1/tickets/{t1}/referencias  (lista)
r6 = client.get(
    f"/api/v1/tickets/{t1.id}/referencias",
    headers=_hdr(), cookies=_cookies,
)
_check_eq("GET /tickets/{}/referencias → 200".format(t1.id),
          200, r6.status_code)
if r6.status_code == 200:
    lista = r6.json()
    _check("lista no vacía", len(lista) > 0,
           f"got {len(lista)} referencias")
    _check_eq("total referencias t1 = 3", 3, len(lista))

# 15.8 GET /api/v1/tickets/{t1}/referencias/resumen
r7 = client.get(
    f"/api/v1/tickets/{t1.id}/referencias/resumen",
    headers=_hdr(), cookies=_cookies,
)
_check_eq("GET resumen → 200", 200, r7.status_code)
if r7.status_code == 200:
    body = r7.json()
    _check_eq("resumen total = 3", 3, body.get("total"))
    _check_eq("resumen salientes = 2", 2, body.get("salientes"))
    _check_eq("resumen entrantes = 1", 1, body.get("entrantes"))

# 15.9 DELETE /api/v1/referencias/{id}  (eliminar la recién creada)
if created_id:
    r8 = client.delete(
        f"/api/v1/referencias/{created_id}",
        headers=_hdr(), cookies=_cookies,
    )
    _check_eq("DELETE ref creada → 200", 200, r8.status_code)

# 15.10 DELETE ref inexistente → 404
r9 = client.delete(
    "/api/v1/referencias/999999", headers=_hdr(), cookies=_cookies,
)
_check_eq("DELETE ref inexistente → 404", 404, r9.status_code)

# 15.11 GET /api/v1/tickets/buscar?q=REF&excluir={t1.id}
# FIX 2026-09-29: el endpoint ya NO está shadowed porque
# referencias.router_tickets se registra ANTES que tickets.router en
# app/api/v1/router.py (FastAPI matchea rutas en orden de registro).
# Esto elimina el toast genérico "Error al guardar el cambio" que
# aparecía al pulsar BUSCAR en el modal de Referencias Internas.
from app.api.v1.referencias import router_tickets as _ref_tickets_router
_rutas_buscar = [
    r.path for r in _ref_tickets_router.routes
    if hasattr(r, "path") and "buscar" in r.path
]
_check(
    "ruta /buscar registrada en router_tickets",
    any(p.endswith("/buscar") for p in _rutas_buscar),
    f"rutas encontradas: {_rutas_buscar}",
)

# Test HTTP directo al endpoint (antes era 422 por shadowing, ahora 200)
r_bus = client.get(
    "/api/v1/tickets/buscar",
    params={"q": "REF", "excluir": str(t1.id)},
    headers=_hdr(), cookies=_cookies,
)
_check_eq(
    "GET /api/v1/tickets/buscar HTTP → 200 (sin shadowing)",
    200, r_bus.status_code,
)
data_bus = r_bus.json()
_check_eq("GET /tickets/buscar → 3 resultados (excluye t1)", 3, len(data_bus))
_codigos_buscar = {x["codigo"] for x in data_bus}
_check(
    "GET /tickets/buscar excluye t1",
    "REF-001" not in _codigos_buscar,
    f"codigos retornados: {_codigos_buscar}",
)

# Test HTMX (debe devolver HTML con clase ref-search-option)
r_bus_htmx = client.get(
    "/api/v1/tickets/buscar",
    params={"q": "REF"},
    headers={**_hdr(), "HX-Request": "true"}, cookies=_cookies,
)
_check_eq(
    "GET /tickets/buscar + HX-Request → 200",
    200, r_bus_htmx.status_code,
)
_check(
    "GET /tickets/buscar HTMX → HTML con ref-search-option",
    "ref-search-option" in r_bus_htmx.text,
)

# 15.12 Smoke test: la función de búsqueda del SERVICE funciona correctamente
from app.services.referencia_service import TicketReferenciaService as _TRS
db_check = SessionLocal()
try:
    _bus = _TRS(db_check).buscar_tickets_para_autocompletar(
        query="REF", exclude_ticket_id=t1.id, limit=50,
    )
    _check_eq("buscar servicio → 3 resultados (excluye t1)",
              3, len(_bus))
finally:
    db_check.close()

# 15.13 Verificar que el helper HTML produce el formato esperado
from app.api.v1.referencias import _render_search_results_html as _rsh
_html = _rsh(_bus, query="REF")
_check("HTML contiene clase ref-search-option",
       "ref-search-option" in _html)
_check("HTML contiene data-ticket-id",
       "data-ticket-id" in _html)
_check("HTML contiene data-codigo-titulo",
       "data-codigo-titulo" in _html)


# ============================================================================
# RESUMEN
# ============================================================================
print("\n" + "=" * 78)
print(f"  RESUMEN — OK: {_RESULTADOS['ok']}   FAIL: {_RESULTADOS['fail']}")
print("=" * 78)
if _RESULTADOS["errores"]:
    print("\n  Fallos:")
    for e in _RESULTADOS["errores"]:
        print(f"   ✗ {e}")
    sys.exit(1)
else:
    print("  ✓ Todos los escenarios pasaron.")
    sys.exit(0)
