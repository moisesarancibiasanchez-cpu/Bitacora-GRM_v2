"""
Test E2E del flujo completo de Picker de Responsable + Email al mover ticket.

Cubre:
1. Login admin
2. Diagnóstico de usuarios
3. Verificar que el picker devuelve los usuarios activos como <option>
4. PATCH responsable_id
5. Verificar persistencia del responsable
6. Mover ticket a la columna con responsable
7. Verificar creación de Notificación in-app
8. Verificar logueo de email en tmp/app.email.log
"""

import os
import sys
import re
from pathlib import Path

# Forzar DB SQLite en tmp/ para que sea autocontenido
os.environ["DATABASE_URL"] = "sqlite:///./tmp/test_picker.db"
os.environ.setdefault("RESEND_API_KEY", "")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("SMTP_FROM", "")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app.main import app
from app.db.base import Base
from app.db.session import SessionLocal, engine as db_engine
from app.models.usuario import Usuario, RolUsuario
from app.models.espacio import Espacio
from app.models.estado import Estado
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.models.watch import Notificacion
from app.core.security import hash_password

# Importar modelos para que SQLAlchemy los registre en Base.metadata
from app.models import (
    Estado, TransicionEstado, Usuario, Ticket,
    CatalogoTipo, CatalogoItem,
    Etiqueta, Checklist, ChecklistItem, Comentario, MencionUsuario, Adjunto,
    ReglaAutomatizacion,
)
from app.models.espacio import Espacio, Tablero, PermisoTablero, espacio_miembros
from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
from app.models.butler_extras import BotonTarjeta, ComandoProgramado
from app.models.watch import Notificacion, Watch, Reaccion

# Limpiar BD previa
db_file = ROOT / "tmp" / "test_picker.db"
if db_file.exists():
    db_file.unlink()

# Solo crear las tablas (sin seed)
Base.metadata.create_all(bind=db_engine)

client = TestClient(app)
results = {"OK": 0, "FAIL": 0, "WARN": 0}
errors = []


def check(label, cond, detail=""):
    if cond:
        results["OK"] += 1
        print(f"  ✓ {label}")
    else:
        results["FAIL"] += 1
        errors.append(f"{label}: {detail}")
        print(f"  ✗ {label}  -- {detail}")


def warn(label, detail=""):
    results["WARN"] += 1
    print(f"  ⚠ {label}  -- {detail}")


# ============================================================
# SETUP: crear usuarios y tablero
# ============================================================
print("\n=== SETUP: Crear admin, agentes, espacio y tablero ===")

db = SessionLocal()
admin = Usuario(
    username="admin_test",
    email="admin_test@test.com",
    nombre_completo="Administrador Test",
    hashed_password=hash_password("admin123"),
    rol=RolUsuario.ADMINISTRADOR,
    is_active=True,
)
agente1 = Usuario(
    username="agente_test",
    email="agente_test@test.com",
    nombre_completo="Agente Test",
    hashed_password=hash_password("agente123"),
    rol=RolUsuario.AGENTE,
    is_active=True,
)
agente2 = Usuario(
    username="agente_test2",
    email="agente_test2@test.com",
    nombre_completo="Segundo Agente Test",
    hashed_password=hash_password("agente123"),
    rol=RolUsuario.AGENTE,
    is_active=True,
)
db.add_all([admin, agente1, agente2])
db.commit()
agente1_id = agente1.id
agente2_id = agente2.id
admin_id = admin.id
db.close()
print(f"  · admin_id={admin_id}, agente1_id={agente1_id}, agente2_id={agente2_id}")

# ============================================================
# 1) LOGIN ADMIN
# ============================================================
print("\n=== 1) Login admin ===")
r = client.post(
    "/api/v1/auth/login-form",
    data={"username": "admin_test", "password": "admin123"},
    follow_redirects=False,
)
check("Login admin OK", r.status_code == 200, f"status={r.status_code}")
cookies_admin = r.cookies

# ============================================================
# 2) DIAGNÓSTICO DE USUARIOS
# ============================================================
print("\n=== 2) Diagnóstico de usuarios ===")
r = client.get("/api/v1/estados/diagnostico/responsables", cookies=cookies_admin)
check("Diagnóstico accesible", r.status_code == 200, f"status={r.status_code}")
diag = r.json()
print(f"  · Diagnóstico: {diag.get('usuarios', {})}")

# ============================================================
# 3) CREAR ESPACIO + TABLERO + ESTADOS
# ============================================================
print("\n=== 3) Crear espacio, tablero y columnas ===")
db = SessionLocal()
espacio = Espacio(
    nombre="Espacio Test",
    plan="gratis",
    es_publico=False,
    propietario_id=admin_id,
    color="#6366f1",
    icono="espacio",
)
db.add(espacio)
db.commit()
espacio_id = espacio.id

from app.models.espacio import Espacio, Tablero
tablero = Tablero(
    nombre="Tablero Test",
    descripcion="Test",
    espacio_id=espacio_id,
    propietario_id=admin_id,
    visibilidad="espacio",
    archivado=False,
)
db.add(tablero)
db.commit()
tablero_id = tablero.id

col_a = Estado(nombre="Col A", tablero_id=tablero_id, orden=0, es_inicial=True)
col_b = Estado(nombre="Col B", tablero_id=tablero_id, orden=1)
col_b.responsable_id = None  # explícitamente sin responsable al inicio
db.add_all([col_a, col_b])
db.commit()
col_a_id = col_a.id
col_b_id = col_b.id
db.close()
print(f"  · tablero_id={tablero_id}, col_a_id={col_a_id}, col_b_id={col_b_id}")

# Transición A→B
db = SessionLocal()
from app.models.estado import TransicionEstado
trans = TransicionEstado(
    estado_origen_id=col_a_id,
    estado_destino_id=col_b_id,
    rol_requerido="agente",
)
db.add(trans)
db.commit()
db.close()

# Crear ticket
db = SessionLocal()
ticket = Ticket(
    codigo="TST-001",
    titulo="Ticket de prueba",
    descripcion="Test ticket",
    estado_id=col_a_id,
    creador_id=admin_id,
    tablero_id=tablero_id,
    tipo=TipoIncidencia.INCIDENCIA,
    prioridad=Prioridad.MEDIA,
)
db.add(ticket)
db.commit()
ticket_id = ticket.id
db.close()
print(f"  · ticket_id={ticket_id}")

# ============================================================
# 4) ABRIR PICKER (GET) - DUMP HTML REAL
# ============================================================
print("\n=== 4) GET picker (HTML response) ===")
r = client.get(
    f"/api/v1/estados/{col_b_id}/responsable-picker",
    cookies=cookies_admin,
)
check("Picker GET OK", r.status_code == 200, f"status={r.status_code}, body={r.text[:200]}")
html = r.text
print(f"  --- HTML devuelto (primeros 600 chars) ---")
print(html[:600])
print(f"  --- FIN HTML ---")

# Contar opciones de <option>
options = re.findall(r'<option\s+value="([^"]+)"[^>]*>([^<]+)</option>', html)
print(f"  · {len(options)} opciones <option> encontradas:")
for v, t in options:
    print(f"      [{v}] {t}")

check(
    f"Picker tiene opción para agente1 ({agente1_id})",
    any(str(agente1_id) == v for v, _ in options),
    f"options={[v for v,_ in options]}",
)
check(
    f"Picker tiene opción para agente2 ({agente2_id})",
    any(str(agente2_id) == v for v, _ in options),
    f"options={[v for v,_ in options]}",
)
check(
    "Picker tiene opción '— Sin responsable —'",
    any("Sin responsable" in t for _, t in options),
    f"options={[t for _,t in options]}",
)

# Verificar el HTML5 form attribute en el <select>
form_attr_match = re.search(r'<select[^>]+form="form-resp-(\d+)"', html)
check(
    "Select tiene atributo HTML5 form= apunta a form-resp-{id}",
    form_attr_match is not None,
    f"html={html[:300]}",
)
onchange_match = re.search(r'onchange="this\.form\.requestSubmit\(\)"', html)
check(
    "Select tiene onchange=this.form.requestSubmit()",
    onchange_match is not None,
    f"onchange_match={onchange_match}",
)

# ============================================================
# 5) PATCH RESPONSABLE - asignar agente1 a col_b
# ============================================================
print("\n=== 5) PATCH responsable_id ===")
r = client.patch(
    f"/api/v1/estados/{col_b_id}",
    data={"responsable_id": str(agente1_id)},
    cookies=cookies_admin,
    headers={"HX-Request": "true"},
)
check(f"PATCH responsable_id={agente1_id} OK", r.status_code == 200, f"status={r.status_code}")

# Verificar persistencia
db = SessionLocal()
estado_b = db.query(Estado).filter(Estado.id == col_b_id).first()
check(
    "responsable_id persistido en BD",
    estado_b.responsable_id == agente1_id,
    f"esperado={agente1_id}, real={estado_b.responsable_id}",
)
db.close()

# ============================================================
# 6) MOVER TICKET A COL_B (con responsable)
# ============================================================
print("\n=== 6) Mover ticket A→B (debe disparar notificación + email) ===")
# Limpiar log de email previo
log_file = ROOT / "tmp" / "app.email.log"
if log_file.exists():
    log_file.unlink()

# Eliminar notificaciones previas
db = SessionLocal()
db.query(Notificacion).filter(Notificacion.ticket_id == ticket_id).delete()
db.commit()
db.close()

# Mover ticket
from app.services.ticket_service import TicketService
db = SessionLocal()
svc = TicketService(db)
admin_usr = db.query(Usuario).filter(Usuario.id == admin_id).first()
ticket_obj, task_id = svc.cambiar_estado(
    ticket_id=ticket_id,
    estado_destino_id=col_b_id,
    usuario=admin_usr,
    comentario="E2E test move",
)
db.close()
check("Ticket movido A→B", ticket_obj.estado_id == col_b_id, f"estado_id={ticket_obj.estado_id}")

# ============================================================
# 7) VERIFICAR NOTIFICACIÓN IN-APP CREADA
# ============================================================
print("\n=== 7) Verificar notificación in-app ===")
db = SessionLocal()
notifs = db.query(Notificacion).filter(Notificacion.ticket_id == ticket_id).all()
check("Notificación creada", len(notifs) >= 1, f"encontradas={len(notifs)}")
for n in notifs:
    print(f"  · Notif id={n.id} -> user={n.usuario_id} titulo='{n.titulo}' tipo={n.tipo}")
if notifs:
    check(
        "Notificación es para el responsable (agente1)",
        notifs[0].usuario_id == agente1_id,
        f"esperado={agente1_id}, real={notifs[0].usuario_id}",
    )
    check(
        "Notificación tipo 'estado'",
        notifs[0].tipo == "estado",
        f"tipo={notifs[0].tipo}",
    )
    check(
        "Notificación menciona Col B",
        "Col B" in (notifs[0].titulo or ""),
        f"titulo={notifs[0].titulo}",
    )
db.close()

# ============================================================
# 8) VERIFICAR EMAIL LOGUEADO EN tmp/app.email.log
# ============================================================
print("\n=== 8) Verificar email logueado ===")
check("Log file existe", log_file.exists(), f"path={log_file}")
if log_file.exists():
    log_content = log_file.read_text()
    print(f"  --- LOG CONTENT ---")
    print(log_content[:1500])
    print(f"  --- FIN LOG ---")
    check(
        "Email contiene 'Para:'",
        "Para:" in log_content,
        f"log={log_content[:200]}",
    )
    check(
        "Email contiene 'Col B' en el asunto",
        "Col B" in log_content,
        f"log={log_content[:200]}",
    )
    check(
        f"Email para agente1 ({agente1.email})",
        agente1.email in log_content,
        f"esperado email={agente1.email}, log={log_content[:300]}",
    )
    check(
        "Email usa transporte 'log' (no SMTP/Resend en este test)",
        "[LOG]" in log_content or "log" in log_content.lower(),
        f"log={log_content[:200]}",
    )

# ============================================================
# 9) PROBAR FLUJO INVERSO: PATCH responsable_id=null
# ============================================================
print("\n=== 9) PATCH responsable_id=null (quitar responsable) ===")
r = client.patch(
    f"/api/v1/estados/{col_b_id}",
    data={"responsable_id": ""},  # string vacío = null
    cookies=cookies_admin,
    headers={"HX-Request": "true"},
)
check(f"PATCH responsable_id='' OK", r.status_code == 200, f"status={r.status_code}")
db = SessionLocal()
estado_b = db.query(Estado).filter(Estado.id == col_b_id).first()
check(
    "responsable_id limpiado en BD",
    estado_b.responsable_id is None,
    f"esperado=None, real={estado_b.responsable_id}",
)
db.close()

# ============================================================
# 10) MOVER TICKET A COL_B SIN RESPONSABLE - NO debe notificar
# ============================================================
print("\n=== 10) Mover ticket a col SIN responsable - NO debe notificar ===")
# Limpiar notificaciones y log
db = SessionLocal()
db.query(Notificacion).filter(Notificacion.ticket_id == ticket_id).delete()
db.commit()
db.close()
if log_file.exists():
    log_file.unlink()

# Crear nueva col C con transicion desde B
db = SessionLocal()
col_c = Estado(nombre="Col C", tablero_id=tablero_id, orden=2)
db.add(col_c)
db.commit()
col_c_id = col_c.id
trans2 = TransicionEstado(
    estado_origen_id=col_b_id,
    estado_destino_id=col_c_id,
    rol_requerido="agente",
)
db.add(trans2)
db.commit()
db.close()

# Mover ticket de B (sin responsable) a C (sin responsable)
db = SessionLocal()
svc = TicketService(db)
admin_usr = db.query(Usuario).filter(Usuario.id == admin_id).first()
ticket_obj, _ = svc.cambiar_estado(
    ticket_id=ticket_id,
    estado_destino_id=col_c_id,
    usuario=admin_usr,
    comentario="E2E test move sin resp",
)
db.close()

# Verificar que NO se creó notificación (porque col C no tiene responsable)
db = SessionLocal()
notifs = db.query(Notificacion).filter(Notificacion.ticket_id == ticket_id).all()
check(
    "NO se creó notificación al mover a col sin responsable",
    len(notifs) == 0,
    f"esperado=0, real={len(notifs)}",
)
db.close()
check(
    "NO se logueó email al mover a col sin responsable",
    not log_file.exists() or log_file.stat().st_size == 0,
    f"log_file={log_file}, exists={log_file.exists()}, size={log_file.stat().st_size if log_file.exists() else 0}",
)

# ============================================================
# 11) VERIFICAR DIAGNOSTICO FINAL
# ============================================================
print("\n=== 11) Diagnóstico final ===")
r = client.get("/api/v1/estados/diagnostico/responsables", cookies=cookies_admin)
check("Diagnóstico final accesible", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    diag = r.json()
    print(f"  · Diagnóstico: {diag}")
    check(
        "email.transporte_activo == 'log'",
        diag.get("email", {}).get("transporte_activo") == "log",
        f"transporte={diag.get('email', {}).get('transporte_activo')}",
    )

# ============================================================
# RESUMEN
# ============================================================
print("\n" + "=" * 70)
print(f"RESUMEN: OK={results['OK']}, FAIL={results['FAIL']}, WARN={results['WARN']}")
print("=" * 70)
if errors:
    print("\nERRORES:")
    for e in errors:
        print(f"  ✗ {e}")

# Cleanup
db_file.unlink(missing_ok=True)
log_file.unlink(missing_ok=True)
db_engine.dispose()

sys.exit(0 if results["FAIL"] == 0 else 1)